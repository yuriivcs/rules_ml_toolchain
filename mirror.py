#!/usr/bin/env python
# pylint: disable=line-too-long
# pylint: disable=missing-function-docstring
"""Automatically mirror TF and JAX dependencies from Bazel WORKSPACE or Bzlmod.

Use this script like this, from the root of the TF or JAX git repository:
  For WORKSPACE:
    bazel query 'kind(tf_http_archive, //external:*) union kind(cuda_nccl_repo,
    //external:*) union kind(_redist_json, //external:*)
    union kind(mirrored_http_archive, //external:*)' --output xml >
    /tmp/sources.xml

  For Bzlmod:
    bazel mod show_repo --all_repos --output=streamed_jsonproto >
    /tmp/sources.json
    python3 mirror.py --bzlmod /tmp/sources.json [optional: space-separated list
    of archives to upload]

  export UPLOAD=true
  python3 mirror.py /tmp/sources.xml [optional: space-separated list of archives
  to upload]

For safety, this script does not upload anything by default. To enable uploads,
set the environment variable UPLOAD=true. If not set, or if set to any other
value, no upload will occur.

Given an XML tree or streamed JSON protobuf representing all of the
tf_http_archive, cuda_nccl_repo and _redist_json rules in TF's or JAX's
repository, ensure all archives are actually uploaded to the TensorFlow mirror
GCS storage bucket (mirror.tensorflow.org).

You may follow the XML or JSON filepath with a space-separated list of archives
to check and re-upload, if you are trying to run this locally. The list should
match the name of the tf_http_archive, cuda_nccl_repo or _redist_json rule.
For example:

  python3 mirror.py /tmp/sources.xml gif XNNPACK

The tf_http_archive() rule ensures that two URLs are always provided in the
same order: a reliable mirror URL first, and the original source URL second.
See google3/third_party/tensorflow/third_party/repo.bzl. However, while
all rules have those URLs _set_, they are not always valid, because developers
don't know what you need to upload the files to the mirror yourself.

This tool parses the XML output from a bazel query and performs the uploads
automatically, after doing some basic hash verification:

  - If the mirror and source URL are identical, the file is skipped. Some rules
    provide the same URL twice, as their source URLs are already pointing to a
    GCS bucket, in which case a second mirror is redundant.
  - If there is an error downloading the source file, the upload is skipped.
  - If a mirror is already present, it is not re-uploaded.
  - If the actual hash of the source URL is different from the Bazel known path,
    the file is skipped. This is an unlikely error, as TensorFlow's build would
    be failing if the hash did not match.

Note again that DOWNLOAD errors are ignored. Only UPLOAD errors cause the
script invocation to fail.

If a file already exists within the cache the upload will fail with a 412 failed
precondition.
See: https://cloud.google.com/storage/docs/request-preconditions#special-case
This prevents a race condition between multiple runs of the job.  To bypass
this restriction for a manual run please

  export ALLOW_OVERWRITE=true
"""

import argparse
import dataclasses
import hashlib
import json
import lzma
import os
import re
import shutil
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

from google.cloud import storage
import requests

CUDA_KEYS = ["cuda11", "cuda12", "cuda13"]
REDIST_PATH_PREFIXES = {
    "standalone_cuda_redist_json": (
        "https://developer.download.nvidia.com/compute/cuda/redist/"
    ),
    "cudnn_redist_json": (
        "https://developer.download.nvidia.com/compute/cudnn/redist/"
    ),
    "nvshmem_redist_json": (
        "https://developer.download.nvidia.com/compute/nvshmem/redist/"
    ),
    "cuda_umd_redist_json": (
        "https://developer.download.nvidia.com/compute/cuda/redist/"
    ),
}
MIRROR_BUCKET_NAME = "mirror.tensorflow.org"
MIRROR_URL_PREFIX = "https://storage.googleapis.com/mirror.tensorflow.org/"

upload = os.environ.get("UPLOAD")
debug = os.environ.get("DEBUG", "0")
allow_overwrite = os.environ.get("ALLOW_OVERWRITE")
bucket = storage.Client().get_bucket(MIRROR_BUCKET_NAME)


@dataclasses.dataclass(frozen=True)
class MirrorEntry:
  sha: str
  mirror: str
  source: str
  name: str


@dataclasses.dataclass(frozen=True)
class CudaMirrorEntry:
  sha: str
  mirror: str
  source: str
  name: str
  file_name: str
  os_name: str
  cuda_key: str


def _get_mirror_urls(url):
  base = re.sub(r"^https?:\/\/", "", url)
  return [
      "https://storage.googleapis.com/mirror.tensorflow.org/%s" % base,
      url,
  ]


def _get_json_attribute(rule_obj, attr_name):
  for attr in rule_obj.get("attribute", []):
    if attr.get("name") == attr_name:
      return attr
  return None


def _create_entry_for_tf_http_archive(archive_rule):
  if isinstance(archive_rule, dict):
    sha = _get_json_attribute(archive_rule, "sha256")["stringValue"]
    urls = _get_json_attribute(archive_rule, "urls")["stringListValue"]
    archive_name = (
        archive_rule.get("originalName")
        or archive_rule.get("canonicalName", "").split("+")[-1]
    )
    return MirrorEntry(
        sha=sha,
        mirror=urls[0],
        source=urls[1] if len(urls) >= 2 else urls[0],
        name=archive_name,
    )
  return MirrorEntry(
      sha=archive_rule.find('.//string[@name="sha256"]').attrib["value"],
      mirror=archive_rule.find('.//list[@name="urls"]')[0].attrib["value"],
      source=archive_rule.find('.//list[@name="urls"]')[1].attrib["value"],
      name=archive_rule.find('.//string[@name="name"]').attrib["value"],
  )


def _create_entry_for_mirrored_http_archive(archive_rule):
  if isinstance(archive_rule, dict):
    urls = _get_json_attribute(archive_rule, "urls")["stringListValue"]
    mirror_url = urls[0]
    source_url = urls[1] if len(urls) >= 2 else mirror_url
    print("_create_entry_for_mirrored_http_archive: ")
    sha = _get_json_attribute(archive_rule, "sha256")["stringValue"]
    return MirrorEntry(
        sha=sha,
        mirror=mirror_url,
        source=source_url,
        name=mirror_url.split("/")[-1],
    )
  urls = archive_rule.find('.//list[@name="urls"]')
  mirror_url = urls[0].attrib["value"]
  if len(urls) == 2:
    source_url = urls[1].attrib["value"]
  else:
    source_url = mirror_url
  return MirrorEntry(
      sha=archive_rule.find('.//string[@name="sha256"]').attrib["value"],
      mirror=mirror_url,
      source=source_url,
      name=mirror_url.split("/")[-1],
  )


def _create_entries_for_cuda_nccl_repo(nccl_repo_rule):
  nccl_repo_entries = []
  if isinstance(nccl_repo_rule, dict):
    dist_name = (
        nccl_repo_rule.get("originalName")
        or nccl_repo_rule.get("canonicalName", "").split("+")[-1]
    )
    url_dict = _get_json_attribute(nccl_repo_rule, "url_dict")["stringDictValue"]
    sha256_dict = _get_json_attribute(nccl_repo_rule, "sha256_dict")[
        "stringDictValue"
    ]
    shas = {item["key"]: item["value"] for item in sha256_dict}
    for item in url_dict:
      pair_name = item["key"]
      m, s = _get_mirror_urls(item["value"])
      nccl_repo_entries.append(
          MirrorEntry(
              sha=shas[pair_name],
              mirror=m,
              source=s,
              name=dist_name,
          )
      )
    return nccl_repo_entries
  # An example of cuda_nccl_repo structure with the nodes used in the script:
  # <rule class="cuda_nccl_repo">
  #  <string name="name" value="cuda_nccl"/>
  #  <dict name="sha256_dict">
  #    <pair>
  #      <string value="11.8-x86_64-unknown-linux-gnu"/>
  #      <string value="49d8350629c7888701d1fd200934942671cb5c728f49acc5a0b3a768820bed29"/>
  #    </pair>
  #  </dict>
  #  <dict name="url_dict">
  #    <pair>
  #        <string value="11.8-x86_64-unknown-linux-gnu"/>
  #        <string value="https://files.pythonhosted.org/packages/ac/9a/8b6a28b3b87d5fddab0e92cd835339eb8fbddaa71ae67518c8c1b3d05bae/nvidia_nccl_cu11-2.21.5-py3-none-manylinux2014_x86_64.whl"/>
  #    </pair>
  #  </dict>
  # </rule>
  url_dict = nccl_repo_rule.find('.//dict[@name="url_dict"]')
  sha256_dict = nccl_repo_rule.find('.//dict[@name="sha256_dict"]')
  dist_name = nccl_repo_rule.find('.//string[@name="name"]').attrib["value"]
  shas = {}
  # This one is formatted differently, collapse the sha dictionary first
  for spair in sha256_dict.iter("pair"):
    pairs = spair.findall(".//string")
    pair_name = pairs[0].attrib["value"]
    shas[pair_name] = pairs[1].attrib["value"]

  for upair in url_dict.iter("pair"):
    pairs = upair.findall(".//string")
    pair_name = pairs[0].attrib["value"]
    m, s = _get_mirror_urls(pairs[1].attrib["value"])
    nccl_repo_entries.append(
        MirrorEntry(
            sha=shas[pair_name],
            mirror=m,
            source=s,
            name=dist_name,
        )
    )
  return nccl_repo_entries


def _create_nvidia_entries_dict(nvidia_repo_rule):
  json_to_dist_entries = {}

  # An example of cuda_redist_json, cudnn_redist_json and nvshmem_redist_json
  # structure with the nodes used in the script:
  # <rule class="_redist_json" name="//external:standalone_cuda_redist_json">
  #  <string name="name" value="standalone_cuda_redist_json"/>
  #  <dict name="json_dict">
  #    <pair>
  #      <string value="12.3.2"/>
  #      <list>
  #        <string value="https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.3.2.json"/>
  #        <string value="1b6eacf335dd49803633fed53ef261d62c193e5a56eee5019e7d2f634e39e7ef"/>
  #      </list>
  #    </pair>
  #  </dict>
  # </rule>
  # <rule class="_redist_json" name="//external:cudnn_redist_json">
  #  <string name="name" value="cudnn_redist_json"/>
  #  <dict name="json_dict">
  #    <pair>
  #      <string value="9.1.1"/>
  #      <list>
  #        <string value="https://developer.download.nvidia.com/compute/cudnn/redist/redistrib_9.1.1.json"/>
  #        <string value="d22d569405e5683ff8e563d00d6e8c27e5e6a902c564c23d752b22a8b8b3fe20"/>
  #      </list>
  #    </pair>
  #  </dict>
  # </rule>
  # <rule class="_redist_json" name="//external:nvshmem_redist_json">
  #  <string name="name" value="nvshmem_redist_json"/>
  #  <dict name="json_dict">
  #    <pair>
  #      <string value="3.2.5"/>
  #      <list>
  #        <string value="https://developer.download.nvidia.com/compute/nvshmem/redist/redistrib_3.2.5.json"/>
  #        <string value="6945425d3bfd24de23c045996f93ec720c010379bfd6f0860ac5f2716659442d"/>
  #      </list>
  #    </pair>
  #  </dict>
  # </rule>
  if isinstance(nvidia_repo_rule, dict):
    rule_name = (
        nvidia_repo_rule.get("originalName")
        or nvidia_repo_rule.get("canonicalName", "").split("+")[-1]
    )
    url_dict_items = _get_json_attribute(nvidia_repo_rule, "json_dict")[
        "stringListDictValue"
    ]
    pairs = [
        (item["value"][0], item["value"][1])
        for item in url_dict_items
    ]
  else:
    rule_name = nvidia_repo_rule.find('.//string[@name="name"]').attrib["value"]
    url_dict = nvidia_repo_rule.find('.//dict[@name="json_dict"]')
    pairs = [
        (
            pair.findall(".//string")[1].attrib["value"],
            pair.findall(".//string")[2].attrib["value"],
        )
        for pair in url_dict.iter("pair")
    ]
  for url, sha in pairs:
    m, s = _get_mirror_urls(url)
    json_name = s[s.rfind("/") + 1 :]
    json_dict_key = MirrorEntry(
        sha=sha,
        mirror=m,
        source=s,
        name=json_name,
    )
    nvidia_dist_list = []
    # Save hashes and urls of redistributions in JSON files.
    f = urllib.request.urlopen(s)
    json_content = json.loads(f.read())
    url_prefix = REDIST_PATH_PREFIXES[rule_name]
    for repo_name, repo in json_content.items():
      if not isinstance(repo, dict):
        continue
      for os_name, os_data in repo.items():
        if not isinstance(os_data, dict):
          continue
        # `cuda11` and `cuda12` keys example:
        # "cudnn": {
        #  "name": "NVIDIA CUDA Deep Neural Network library",
        #  "linux-x86_64": {
        #    "cuda11": {
        #      "relative_path": "cudnn/linux-x86_64/cudnn-linux-x86_64-9.1.1.17_cuda11-archive.tar.xz",
        #      "sha256": "15a8b77123c1911606b45703691ad0990892c6098070ffab0bcaa003183a7dcb",
        #    },
        #    "cuda12": {
        #      "relative_path": "cudnn/linux-x86_64/cudnn-linux-x86_64-9.1.1.17_cuda12-archive.tar.xz",
        #      "sha256": "992b4be26899cc4c618bb1f6989261df7d0a9f9032b2217bf1fce9dd3228c904",
        #    }
        #  },
        # }
        for cuda_key in CUDA_KEYS:
          if cuda_key in os_data.keys():
            relative_path = os_data[cuda_key]["relative_path"]
            m, s = _get_mirror_urls(url_prefix + relative_path)
            file_name = relative_path[relative_path.rfind("/") + 1 :]
            nvidia_dist_list.append(
                CudaMirrorEntry(
                    sha=os_data[cuda_key]["sha256"],
                    mirror=m,
                    source=s,
                    name=repo_name,
                    file_name=file_name,
                    os_name=os_name,
                    cuda_key=cuda_key,
                )
            )
        # CUDA and CUDNN redistribution data examples:
        # "cudnn": {
        #   "name": "NVIDIA CUDA Deep Neural Network library",
        #   "linux-x86_64": {
        #     "relative_path": "cudnn/linux-x86_64/cudnn-linux-x86_64-8.9.7.29_cuda12-archive.tar.xz",
        #     "sha256": "475333625c7e42a7af3ca0b2f7506a106e30c93b1aa0081cd9c13efb6e21e3bb",
        #   },
        # }
        #
        # "cuda_cccl": {
        #   "name": "CXX Core Compute Libraries",
        #   "linux-x86_64": {
        #     "relative_path": "cuda_cccl/linux-x86_64/cuda_cccl-linux-x86_64-12.3.101-archive.tar.xz",
        #     "sha256": "dabd433bbef5f6d1b79f9a7eea909a3c273e20641f07a6a8667f42577462e34d",
        #   },
        # }
        if "sha256" in os_data.keys():
          relative_path = os_data["relative_path"]
          m, s = _get_mirror_urls(url_prefix + relative_path)
          file_name = relative_path[relative_path.rfind("/") + 1 :]
          nvidia_dist_list.append(
              CudaMirrorEntry(
                  sha=os_data["sha256"],
                  mirror=m,
                  source=s,
                  name=repo_name,
                  file_name=file_name,
                  os_name=os_name,
                  cuda_key=None,
              )
          )
    json_to_dist_entries[json_dict_key] = nvidia_dist_list
  return json_to_dist_entries


def _tar_xz_to_tar(xz_file, tar_file):
  with lzma.open(xz_file, mode="rb") as xz_in:
    with open(tar_file.name, "wb") as tar_out:
      tar_out.write(xz_in.read())
  xz_file.seek(0)


def _get_sha256_checksum(file):
  # Replicates hashlib.file_digest(), only available after Python 3.11.
  # See https://docs.python.org/3/library/hashlib.html
  hash_val = hashlib.sha256()
  while True:
    data = file.read(2**18)  # Same as buffer size used in hashlib.file_digest()
    if not data:
      break
    hash_val.update(data)
  file.seek(0)
  return hash_val.hexdigest()


def _verify_source_downloaded_successfully(source_name, source, known_sha, tmp):
  print(f"{source_name}: DOWNLOADING ({source})...")
  if MIRROR_URL_PREFIX in source:
    blob_path = source.replace(MIRROR_URL_PREFIX, "")
    gcs_blob = bucket.get_blob(blob_path)
    gcs_blob.download_to_file(tmp)
  else:
    # Use requests and shutil to efficiently stream the remote source. If not
    # streamed, the program might try and read a large archive into memory,
    # which could crash if the source is really huge.
    try:
      with requests.get(source, stream=True) as r:
        if r.headers["content-type"] == "application/json":
          r.raw.decode_content = True
        shutil.copyfileobj(r.raw, tmp)

    except requests.exceptions.RequestException as e:
      print(
          f"{source_name}: SKIPPED (There was a problem downloading the file:"
          f" {str(e)})"
      )
      return False
  tmp.seek(0)  # Reset file object so it can be re-read

  if known_sha:
    actual_sha = _get_sha256_checksum(tmp)
    if known_sha != actual_sha:
      print(
          f"{source_name}: SKIPPED (Known sha256 is different from the URL's"
          " sha256)"
      )
      print(f"{source_name}: Known sha256:  {known_sha}")
      print(f"{source_name}: Actual sha256: {actual_sha}")
      return False
  return True


def _is_source_present_in_bucket(blob_dist_path, source_name):
  gcs_dist_blob = bucket.get_blob(blob_dist_path)
  if gcs_dist_blob:
    print(f"{source_name}: Already present in tf_mirror bucket")
    return True
  return False


def _print_skip_upload_message(dist_name):
  print(
      f"{dist_name}: The dependencies were set to not be uploaded. If this is"
      " not the intended behavior, set the UPLOAD environment variable to"
      " 'true'"
  )


def _print_message_if_dist_is_present_in_mirror(
    dist_name, is_dist_present_in_mirror
):
  if is_dist_present_in_mirror:
    print(f"{dist_name} is already present in mirror and will not be uploaded")
  elif upload == "true":
    print(f"{dist_name} is not present in mirror and marked for upload")
  else:
    print(f"{dist_name} is not present in mirror")


def _upload_dist_if_needed(dist_name, blob_path, tmp):
  if upload != "true":
    _print_skip_upload_message(dist_name)
    return

  print(f"{dist_name}: UPLOADING")
  blob = bucket.blob(blob_path)
  # If ALLOW_OVERWRITE is supplied, try to upload normally. If not, upload
  # in a way that aborts if an identical file has already been (or is
  # currently being) uploaded. This prevents a race condition between
  # similar upload jobs that use the same mirror (e.g. JAX and TensorFlow)
  if allow_overwrite == "true":
    blob.upload_from_file(tmp)
  else:
    blob.upload_from_file(tmp, if_generation_match=0)
  tmp.seek(0)

  print(f"Uploaded {dist_name}")


def _upload_non_nvidia_dist(
    dist_name, source, known_sha, mirror, upload_tar_file=False
):
  # Skip this rule if it's already been uploaded to the mirror at some point in
  # the past (that is, if the mirror URL already has something in it)
  blob_path = mirror.replace(MIRROR_URL_PREFIX, "")
  if _is_source_present_in_bucket(blob_path, dist_name):
    return

  with tempfile.TemporaryFile() as tmp:
    if not _verify_source_downloaded_successfully(
        dist_name, source, known_sha, tmp
    ):
      return

    _upload_dist_if_needed(dist_name, blob_path, tmp)

    if upload_tar_file:
      if not source.endswith(".tar.xz"):
        return

      tar_file_name = dist_name.replace(".tar.xz", ".tar")
      blob_tar_path = mirror.replace(MIRROR_URL_PREFIX, "").replace(
          ".tar.xz", ".tar"
      )
      tar_exists_in_bucket = _is_source_present_in_bucket(
          blob_tar_path, tar_file_name
      )
      _print_message_if_dist_is_present_in_mirror(
          tar_file_name, tar_exists_in_bucket
      )
      with tempfile.NamedTemporaryFile() as tmp_tar_dist_file:
        # Create a tar file by unzipping the tar.xz file.
        _tar_xz_to_tar(tmp, tmp_tar_dist_file)
        # Calculate the sha256sum of the tar file.
        tar_sha256 = _get_sha256_checksum(tmp_tar_dist_file)
        print(f"{tar_file_name} has sha256 {tar_sha256}")

        if not tar_exists_in_bucket:
          # Upload the tar file to the mirror if is not present there.
          _upload_dist_if_needed(
              tar_file_name,
              blob_tar_path,
              tmp_tar_dist_file,
          )


def _create_json_tar_content(json_tmp, tar_sha256_dict):
  json_tar_content = json.load(json_tmp)
  json_tmp.seek(0)

  for dist_name, os_data in tar_sha256_dict.items():
    for os_name, data in os_data.items():
      if isinstance(data, dict):
        for cuda_key, tar_sha in data.items():
          json_tar_content[dist_name][os_name][cuda_key]["sha256"] = tar_sha
          json_tar_content[dist_name][os_name][cuda_key]["relative_path"] = (
              json_tar_content[dist_name][os_name][cuda_key][
                  "relative_path"
              ].replace(".tar.xz", ".tar")
          )
          del json_tar_content[dist_name][os_name][cuda_key]["md5"]
          del json_tar_content[dist_name][os_name][cuda_key]["size"]
      else:
        json_tar_content[dist_name][os_name]["sha256"] = data
        json_tar_content[dist_name][os_name]["relative_path"] = (
            json_tar_content[dist_name][os_name]["relative_path"].replace(
                ".tar.xz", ".tar"
            )
        )
        del json_tar_content[dist_name][os_name]["md5"]
        del json_tar_content[dist_name][os_name]["size"]
  return json_tar_content


def _upload_json_with_tars(json_tar_name, json_tar_content, blob_json_tar_path):
  with tempfile.NamedTemporaryFile() as json_tmp_tar:
    json_tmp_tar.write(json.dumps(json_tar_content).encode("ascii"))
    json_tmp_tar.seek(0)

    actual_sha_json_tar = _get_sha256_checksum(json_tmp_tar)
    # 8. Print the sha256 of the json_tar file.
    print(f"{json_tar_name} has sha256 {actual_sha_json_tar}")

    # 9. Upload the json_tar file to the mirror.
    _upload_dist_if_needed(f"{json_tar_name}", blob_json_tar_path, json_tmp_tar)


def _process_non_nvidia_entries(non_nvidia_entries, upload_tar_file=False):
  for entry in non_nvidia_entries:
    if int(debug) == 1:
      print(f"Processing tuple {entry}")
    mirror = entry.mirror
    source = entry.source
    known_sha = entry.sha
    entry_name = entry.name

    # Ignore the few rules which have identical sources, usually things that
    # were hosted in a bucket in the first place.
    if mirror == source:
      print(f"{entry_name}: SKIPPED (Its mirror and source are identical URLs)")
      continue

    _upload_non_nvidia_dist(
        entry_name, source, known_sha, mirror, upload_tar_file
    )


def _close_all_tmp_nvidia_dist_files(tmp_nvidia_dist_data):
  for _, dist_data in tmp_nvidia_dist_data.items():
    for _, os_data in dist_data.items():
      if "tmp_file" in os_data and os_data["tmp_file"] is not None:
        os_data["tmp_file"].close()
      else:
        for _, cuda_version_data in os_data.items():
          if (
              "tmp_file" in cuda_version_data
              and cuda_version_data["tmp_file"] is not None
          ):
            cuda_version_data["tmp_file"].close()


def save_nvidia_distribution_data(
    dist_name, os_name, cuda_key, data_dict, value
):
  if dist_name not in data_dict:
    data_dict[dist_name] = {}
  if os_name not in data_dict[dist_name] and cuda_key:
    data_dict[dist_name][os_name] = {}
  if cuda_key:
    data_dict[dist_name][os_name][cuda_key] = value
  else:
    data_dict[dist_name][os_name] = value


def get_nvidia_distribution_data(dist_name, os_name, cuda_key, data_dict):
  if cuda_key:
    return data_dict[dist_name][os_name][cuda_key]
  else:
    return data_dict[dist_name][os_name]


def _upload_nvidia_dist_tars(nvidia_dist_entries, tmp_nvidia_dist_data):
  tar_sha256_data = {}
  for entry in nvidia_dist_entries:
    mirror = entry.mirror
    source = entry.source
    dist_name = entry.name
    os_name = entry.os_name
    cuda_key = entry.cuda_key
    tar_file_name = entry.file_name.replace(".tar.xz", ".tar")

    if not source.endswith(".tar.xz"):
      continue

    blob_tar_path = mirror.replace(MIRROR_URL_PREFIX, "").replace(
        ".tar.xz", ".tar"
    )
    tar_exists_in_bucket = _is_source_present_in_bucket(
        blob_tar_path, tar_file_name
    )
    _print_message_if_dist_is_present_in_mirror(
        tar_file_name, tar_exists_in_bucket
    )

    tmp_nvidia_dist_file = get_nvidia_distribution_data(
        dist_name, os_name, cuda_key, tmp_nvidia_dist_data
    )["tmp_file"]

    with tempfile.NamedTemporaryFile() as tmp_tar_nvidia_dist_file:
      # 6a. Create a tar file by unzipping the tar.xz file.
      _tar_xz_to_tar(tmp_nvidia_dist_file, tmp_tar_nvidia_dist_file)
      # 6b. Calculate the sha256sum of the tar file and save it in a dictionary.
      tar_sha256 = _get_sha256_checksum(tmp_tar_nvidia_dist_file)
      print(f"{tar_file_name} has sha256 {tar_sha256}")
      if not tar_exists_in_bucket:
        # 6c. Upload the tar file to the mirror if is not present there.
        _upload_dist_if_needed(
            tar_file_name,
            blob_tar_path,
            tmp_tar_nvidia_dist_file,
        )

      save_nvidia_distribution_data(
          dist_name, os_name, cuda_key, tar_sha256_data, tar_sha256
      )

  return tar_sha256_data


def _upload_nvidia_dist_entries(nvidia_dist_entries):
  tmp_nvidia_dist_data = {}
  for entry in nvidia_dist_entries:
    if int(debug) == 1:
      print(f"Processing tuple {entry}")
    mirror = entry.mirror
    source = entry.source
    known_sha = entry.sha
    dist_name = entry.name
    os_name = entry.os_name
    cuda_key = entry.cuda_key
    file_name = entry.file_name

    blob_path = mirror.replace(MIRROR_URL_PREFIX, "")
    dist_exists_in_bucket = _is_source_present_in_bucket(blob_path, file_name)
    _print_message_if_dist_is_present_in_mirror(
        file_name, dist_exists_in_bucket
    )

    tmp_nvidia_dist_file = tempfile.NamedTemporaryFile()
    # 4a. Download the distribution and compare its sha256sum with the known
    #     sha256sum in the entry. If the distribution wasn't downloaded
    #     successfully or the sha256sums are not equal, skip the rest of the
    #     steps.
    if not _verify_source_downloaded_successfully(
        file_name,
        source,
        known_sha,
        tmp_nvidia_dist_file,
    ):
      tmp_nvidia_dist_file.close()
      _close_all_tmp_nvidia_dist_files(tmp_nvidia_dist_data)
      return None

    # 4b. Save the downloaded distribution in a temporary file and save it in
    #     a dictionary.
    save_nvidia_distribution_data(
        dist_name,
        os_name,
        cuda_key,
        tmp_nvidia_dist_data,
        {
            "tmp_file": tmp_nvidia_dist_file,
            "mirror": mirror,
            "source": source,
        },
    )

    if not dist_exists_in_bucket:
      # 4c. Upload the distribution to the mirror if is not present there.
      _upload_dist_if_needed(file_name, blob_path, tmp_nvidia_dist_file)
  return tmp_nvidia_dist_data


def _process_nvidia_entries(nvidia_json_to_distribution_entries):
  for json_entry, dist_entries in nvidia_json_to_distribution_entries.items():
    json_mirror = json_entry.mirror
    json_source = json_entry.source
    json_known_sha = json_entry.sha
    json_name = json_entry.name

    # The following steps are executed:
    # 0. Check if the json_tar file is present in gcs. If it is, we can skip
    #    the rest of the processing.
    # 1. Download the json file from the original source.
    # 2. Skip the rest of the steps if the json file was not downloaded
    #    successfully.
    # 3. Iterate over the distribution entries in the json file.
    # 4. For each distribution entry, do the following:
    # 4a. Download the distribution and compare its sha256sum with the known
    #     sha256sum in the entry. If the distribution wasn't downloaded
    #     successfully or the sha256sums are not equal, skip the rest of the
    #     steps.
    # 4b. Save the downloaded distribution in a temporary file and save it in
    #     a dictionary.
    # 4c. Upload the distribution to the mirror if is not present there.
    # 5. Upload the json file to the mirror if is not present there.
    # 6. For each tar.xz distribution entry, do the following:
    # 6a. Create a tar file by unzipping the tar.xz file.
    # 6b. Calculate the sha256sum of the tar file and save it in a dictionary.
    # 6c. Upload the tar file to the mirror if is not present there.
    # 7. Create a json_tar file with .tar files sha256sums.
    # 8. Upload the json_tar file to the mirror.
    # 9. Print the sha256 of the json_tar file.

    blob_json_tar_path = json_mirror.replace(MIRROR_URL_PREFIX, "").replace(
        ".json", "_tar.json"
    )
    json_tar_name = json_name.replace(".json", "_tar.json")
    skip_uploading_json_tar = _is_source_present_in_bucket(
        blob_json_tar_path, f"{json_tar_name}"
    )
    _print_message_if_dist_is_present_in_mirror(
        json_tar_name, skip_uploading_json_tar
    )
    # 0. Check if the json_tar file is present in gcs. If it is, we can skip
    #    the rest of the processing.
    if skip_uploading_json_tar:
      continue

    # Check if original json is present in gcs.
    blob_json_path = json_mirror.replace(MIRROR_URL_PREFIX, "")
    skip_uploading_json = _is_source_present_in_bucket(
        blob_json_path, json_name
    )
    _print_message_if_dist_is_present_in_mirror(json_name, skip_uploading_json)

    with tempfile.NamedTemporaryFile() as json_tmp:

      tmp_nvidia_dist_data = {}
      try:
        # 1. Download the json file from the original source.
        # 2. Skip the rest of the steps if the json file was not downloaded
        #    successfully.
        if not _verify_source_downloaded_successfully(
            json_name, json_source, json_known_sha, json_tmp
        ):
          continue

        # 3. Iterate over the distribution entries in the json file.
        tmp_nvidia_dist_data = _upload_nvidia_dist_entries(dist_entries)
        if tmp_nvidia_dist_data is None:
          print(f"Failed to upload CUDA dist entries for {json_name}, skipping")
          continue
        if int(debug) == 1:
          print(f"Processing tuple {json_entry}")
        if not skip_uploading_json:
          # 5. Upload the json file to the mirror if is not present there.
          _upload_dist_if_needed(json_name, blob_json_path, json_tmp)

        tar_sha256_data = _upload_nvidia_dist_tars(
            dist_entries, tmp_nvidia_dist_data
        )
        # 7. Create a json_tar file with .tar files sha256sums.
        json_tar_content = _create_json_tar_content(json_tmp, tar_sha256_data)
        _upload_json_with_tars(
            json_tar_name, json_tar_content, blob_json_tar_path
        )
      finally:
        _close_all_tmp_nvidia_dist_files(tmp_nvidia_dist_data)


def _load_rules(filepath, is_bzlmod=False):
  if is_bzlmod:
    with open(filepath, "r", encoding="utf-8") as f:
      for line in f:
        stripped = line.strip()
        print("_load_rules(json): ", stripped)
        if stripped:
          yield json.loads(stripped)
  else:
    for xml_rule in ET.parse(filepath).getroot():
      print("_load_rules(xml): ", xml_rule)
      yield xml_rule


def _get_rule_class(rule_obj):
  if isinstance(rule_obj, dict):
    return rule_obj.get("repoRuleName")
  return rule_obj.attrib["class"]


def _parse_args(argv=None):
  parser = argparse.ArgumentParser(
      description="Automatically mirror TF or JAX dependencies from Bazel."
  )
  parser.add_argument(
      "--bzlmod",
      action="store_true",
      help=(
          "Parse streamed JSON protobuf output from bazel mod show_repo instead"
          " of XML."
      ),
  )
  parser.add_argument(
      "filepath",
      help="Path to the XML (WORKSPACE) or JSON (Bzlmod) file.",
  )
  parser.add_argument(
      "requested",
      nargs="*",
      help="Optional space-separated list of archives to process.",
  )
  return parser.parse_args(argv)


def main(argv=None):
  args = _parse_args(argv)
  requested = args.requested

  for rule in _load_rules(args.filepath, is_bzlmod=args.bzlmod):
    entries = []
    mirrored_entries = []
    nvidia_entries_dict = {}
    name = ""

    rule_class = _get_rule_class(rule)
    if rule_class in ["_tf_http_archive", "tf_http_archive"]:
      tf_http_archive_entry = _create_entry_for_tf_http_archive(rule)
      name = tf_http_archive_entry.name
      entries.append(tf_http_archive_entry)
    elif rule_class == "cuda_nccl_repo":
      try:
        cuda_nccl_repo_entries = _create_entries_for_cuda_nccl_repo(rule)
        name = cuda_nccl_repo_entries[0].name
        entries.extend(cuda_nccl_repo_entries)
      except (IndexError, KeyError):
        print("Failed to create entries for cuda_nccl_repo")
    elif rule_class == "_redist_json":
      try:
        name = "_redist_json"
        nvidia_entries_dict = _create_nvidia_entries_dict(rule)
      except (IndexError, KeyError):
        print("Failed to create entries for _redist_json")
    elif rule_class == "mirrored_http_archive":
      mirrored_http_archive_entry = _create_entry_for_mirrored_http_archive(rule)
      name = mirrored_http_archive_entry.name
      mirrored_entries.append(mirrored_http_archive_entry)

    # If any archives were explicitly specified, quietly skip non-matching
    # archives.
    if requested and name not in requested:
      continue

    _process_non_nvidia_entries(entries, upload_tar_file=False)

    _process_nvidia_entries(nvidia_entries_dict)

    _process_non_nvidia_entries(mirrored_entries, upload_tar_file=True)


if __name__ == "__main__":
  main()

