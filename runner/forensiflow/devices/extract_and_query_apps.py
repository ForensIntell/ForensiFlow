#!/usr/bin/env python3
"""
设备应用信息提取工具

功能：
1. 从 Android 设备获取所有已安装应用的包名
2. 批量查询应用详细信息
3. 生成应用列表文件和映射关系

使用示例：
    # 查询所有应用
    python extract_and_query_apps.py

    # 只查询第三方应用
    python extract_and_query_apps.py --third-party

    # 指定包名查询
    python extract_and_query_apps.py --packages com.whatsapp com.tencent.mm
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app_info_fetcher import AppInfoFetcher


def get_installed_packages(device_id: str = None, third_party_only: bool = False) -> list:
    """
    获取设备上已安装应用的包名列表

    Args:
        device_id: 设备ID（多设备时使用）
        third_party_only: 是否只获取第三方应用

    Returns:
        包名列表
    """
    try:
        # 构建 adb 命令
        cmd = ["adb"]
        if device_id:
            cmd.extend(["-s", device_id])

        # 获取包名列表
        if third_party_only:
            cmd.extend(["shell", "pm", "list", "packages", "-3"])
        else:
            cmd.extend(["shell", "pm", "list", "packages"])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logging.error(f"ADB 命令执行失败: {result.stderr}")
            return []

        # 解析输出
        # 输出格式: package:com.whatsapp
        packages = []
        for line in result.stdout.strip().split('\n'):
            if line.startswith('package:'):
                package_name = line.replace('package:', '').strip()
                packages.append(package_name)

        logging.info(f"✅ 获取到 {len(packages)} 个应用包名")
        return packages

    except subprocess.TimeoutExpired:
        logging.error("❌ ADB 命令超时")
        return []
    except Exception as e:
        logging.error(f"❌ 获取包名失败: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="设备应用信息提取工具")
    parser.add_argument(
        "--device",
        type=str,
        help="指定设备ID（多设备时使用）"
    )
    parser.add_argument(
        "--third-party",
        action="store_true",
        help="只获取第三方应用（排除系统应用）"
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        help="直接指定要查询的包名列表"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="每次查询之间的延迟（秒），默认1.5秒"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/app_info",
        help="输出目录，默认 ./data/app_info"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="强制刷新缓存（不使用旧缓存）"
    )

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 80)
    print("📱 设备应用信息提取工具")
    print("=" * 80)

    # 获取包名列表
    if args.packages:
        packages = args.packages
        print(f"\n📦 手动指定 {len(packages)} 个包名")
    else:
        print(f"\n📱 正在从设备获取应用列表...")
        packages = get_installed_packages(
            device_id=args.device,
            third_party_only=args.third_party
        )

        if not packages:
            print("❌ 未获取到任何包名，请检查：")
            print("   1. 设备是否已连接")
            print("   2. USB调试是否已开启")
            print("   3. ADB是否正常工作")
            return

    print(f"✅ 共 {len(packages)} 个应用待查询")

    # 初始化查询器
    fetcher = AppInfoFetcher(
        cache_dir=f"{args.output_dir}/cache",
        cache_expiry_hours=24
    )

    # 强制刷新模式
    if args.refresh:
        print("\n🔄 强制刷新模式：跳过缓存")
    else:
        print(f"\n💾 使用缓存模式（缓存过期时间: 24小时）")

    # 批量查询
    print("\n" + "=" * 80)
    print("🔍 开始批量查询应用信息")
    print("=" * 80)

    results = fetcher.fetch_multiple_apps(packages, delay=args.delay)

    print("\n" + "=" * 80)
    print(f"✅ 查询完成: {len(results)}/{len(packages)} 成功")
    print("=" * 80)

    # 生成映射文件
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 导出完整信息 (TXT)
    txt_file = output_dir / "app_info_full.txt"
    fetcher.export_to_txt(str(txt_file))
    print(f"\n📄 完整信息: {txt_file}")

    # 2. 导出JSON格式
    json_file = output_dir / "app_info_full.json"
    fetcher.export_to_json(str(json_file))
    print(f"📄 JSON格式: {json_file}")

    # 3. 生成简化的包名-名称映射
    mapping_file = output_dir / "package_name_mapping.txt"
    with open(mapping_file, 'w', encoding='utf-8') as f:
        f.write("# 包名到应用名称的映射\n")
        f.write(f"# 生成时间: {__import__('datetime').datetime.now()}\n")
        f.write(f"# 总计: {len(results)} 个应用\n")
        f.write("=" * 80 + "\n\n")

        for pkg in sorted(results.keys()):
            app_info = results[pkg]
            title = app_info.get('title', 'Unknown')
            category = app_info.get('category', 'Unknown')

            f.write(f"{pkg}\t{title}\t{category}\n")

    print(f"📄 映射文件: {mapping_file}")

    # 4. 生成包名列表（每行一个）
    list_file = output_dir / "packages.txt"
    with open(list_file, 'w', encoding='utf-8') as f:
        for pkg in sorted(results.keys()):
            f.write(f"{pkg}\n")
    print(f"📄 包名列表: {list_file}")

    # 5. 统计信息
    summary = fetcher.get_summary()
    stats_file = output_dir / "statistics.txt"
    with open(stats_file, 'w', encoding='utf-8') as f:
        f.write("应用信息统计\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"总应用数: {summary['total_apps']}\n\n")

        f.write("分类统计:\n")
        f.write("-" * 80 + "\n")
        for category, count in sorted(
            summary['categories'].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            f.write(f"  {category}: {count}\n")

    print(f"📊 统计信息: {stats_file}")

    # 6. 生成失败列表
    failed_packages = set(packages) - set(results.keys())
    if failed_packages:
        failed_file = output_dir / "failed_packages.txt"
        with open(failed_file, 'w', encoding='utf-8') as f:
            f.write("# 查询失败的包名列表\n")
            f.write(f"# 共 {len(failed_packages)} 个应用查询失败\n\n")
            for pkg in sorted(failed_packages):
                f.write(f"{pkg}\n")
        print(f"⚠️  失败列表: {failed_file} ({len(failed_packages)} 个)")

    print("\n" + "=" * 80)
    print("✅ 所有文件已生成到:", args.output_dir)
    print("=" * 80)


if __name__ == "__main__":
    main()
