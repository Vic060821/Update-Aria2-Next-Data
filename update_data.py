#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能：
  1. 从内置的 LIST1_URLS 列表中读取 URL，并发使用 curl 下载到 LIST1_DOWNLOAD_DIR 目录，
     文件名为 URL 的 basename，自动覆盖已有文件。
  2. 从内置的 LIST2_URLS 列表中读取 tracker 列表 URL，并发使用 curl 下载到临时文件，
     合并、去重、排序，生成逗号分隔的字符串，
     备份原 aria2.conf，然后更新其中的 bt-tracker= 行。
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# ============================================================
# ===== 用户配置区域（请根据实际情况修改） =====================
# ============================================================

# 1. list1 的 URL 列表（下载到统一目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

LIST1_URLS = [
    "https://upd.emule-security.org/nodes.dat",
    "https://upd.emule-security.org/server.met",
]

# 下载目录（文件将直接保存至此，以 URL 末尾的文件名命名）
LIST1_DOWNLOAD_DIR = "./"

# 2. list2 的 tracker 列表 URL（列表）
LIST2_URLS = [
    "https://cdn.jsdelivr.net/gh/XIU2/TrackersListCollection/all.txt",
    "https://cdn.jsdelivr.net/gh/ngosang/trackerslist/trackers_all.txt",
    "https://cdn.jsdelivr.net/gh/ngosang/trackerslist/trackers_all_ip.txt",
]

# 3. aria2 配置文件路径
ARIA2_CONF_PATH = "./aria2.conf"

# ============================================================
# ===== 以下为脚本逻辑，一般无需修改 ============================
# ============================================================

def download_with_curl(url, dest):
    """使用 curl 下载 URL 并保存到 dest（自动覆盖）"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = ['curl', '-L', '-f', '--connect-timeout', '30', '-o', dest, url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"curl 下载失败 (返回码 {result.returncode}): {result.stderr}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"执行 curl 异常: {e}", file=sys.stderr)
        return False

def get_filename_from_url(url):
    """从 URL 中提取文件名（去除查询参数）"""
    parsed = urlparse(url)
    # 取路径的最后一部分作为文件名
    filename = os.path.basename(parsed.path)
    # 如果路径以 '/' 结尾或为空，则使用默认名
    if not filename:
        filename = "downloaded_file"
    return filename

def backup_file(filepath):
    """备份文件为 filepath.bak（若原文件存在）"""
    if os.path.exists(filepath):
        backup_path = filepath + ".bak"
        try:
            shutil.copy2(filepath, backup_path)
            print(f"已备份原配置文件到 {backup_path}")
        except Exception as e:
            print(f"备份失败: {e}", file=sys.stderr)

def update_aria2_tracker(conf_path, tracker_string):
    """
    更新 aria2.conf 中的 bt-tracker= 行。
    如果存在该行，则替换等号后的内容；否则在文件末尾追加一行。
    保留原文件的其余内容不变。
    """
    backup_file(conf_path)

    try:
        with open(conf_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    pattern = re.compile(r'^\s*bt-tracker\s*=', re.IGNORECASE)
    found = False
    new_lines = []
    for line in lines:
        if pattern.search(line):
            new_lines.append(f"bt-tracker={tracker_string}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"bt-tracker={tracker_string}\n")

    with open(conf_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"已更新 {conf_path} 中的 bt-tracker，共 {len(tracker_string.split(','))} 个 tracker。")

def download_list1_concurrently(urls, download_dir):
    """并发下载 list1 中的所有 URL 到指定目录"""
    if not urls:
        print("警告: LIST1_URLS 为空，跳过")
        return

    print(f"开始并发下载 {len(urls)} 个 list1 文件到 {download_dir} ...")
    with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as executor:  # 最多5个并发
        future_to_url = {}
        for url in urls:
            filename = get_filename_from_url(url)
            dest = os.path.join(download_dir, filename)
            future = executor.submit(download_with_curl, url, dest)
            future_to_url[future] = url

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                success = future.result()
                if success:
                    print(f"成功: {url}")
                else:
                    print(f"失败: {url}")
            except Exception as e:
                print(f"下载 {url} 时发生异常: {e}", file=sys.stderr)

def download_list2_concurrently(urls):
    """
    并发下载 list2 中的 tracker 文件到临时目录，然后读取合并去重。
    返回去重后的 tracker 集合。
    """
    if not urls:
        print("警告: LIST2_URLS 为空，跳过")
        return set()

    print(f"开始并发下载 {len(urls)} 个 tracker 列表...")
    temp_dir = tempfile.mkdtemp(prefix="tracker_download_")
    all_lines = set()
    try:
        # 并发下载每个 URL 到临时文件
        with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as executor:
            future_to_url = {}
            for url in urls:
                # 生成临时文件名（使用 hash 避免冲突）
                temp_file = os.path.join(temp_dir, f"tracker_{hash(url)}.txt")
                future = executor.submit(download_with_curl, url, temp_file)
                future_to_url[future] = (url, temp_file)

            for future in as_completed(future_to_url):
                url, temp_file = future_to_url[future]
                try:
                    success = future.result()
                    if success:
                        print(f"下载成功: {url}，开始读取内容...")
                        try:
                            with open(temp_file, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                    line = line.strip()
                                    if line:
                                        all_lines.add(line)
                            print(f"读取成功: {url}")
                        except Exception as e:
                            print(f"读取临时文件 {temp_file} 失败: {e}", file=sys.stderr)
                    else:
                        print(f"下载失败: {url}")
                except Exception as e:
                    print(f"处理 {url} 时发生异常: {e}", file=sys.stderr)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return all_lines

def main():
    # ---------- 并发处理 list1 ----------
    download_list1_concurrently(LIST1_URLS, LIST1_DOWNLOAD_DIR)

    # ---------- 并发处理 list2 ----------
    print("\n" + "=" * 50)
    all_trackers = download_list2_concurrently(LIST2_URLS)

    if all_trackers:
        tracker_str = ",".join(sorted(all_trackers))
        update_aria2_tracker(ARIA2_CONF_PATH, tracker_str)
    else:
        print("警告: 未获取到任何有效 tracker 条目，不更新配置文件")

if __name__ == "__main__":
    main()