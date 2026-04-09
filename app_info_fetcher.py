"""
应用信息查询模块

通过包名从 Google Play 商店动态获取应用信息：
- 应用名称
- 开发者
- 分类
- 功能描述
- 评分、下载量等

支持缓存机制，提高查询效率。
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from google_play_scraper import app, search


class AppInfoFetcher:
    """应用信息查询器"""

    def __init__(
        self,
        cache_dir: str = "./data/app_info_cache",
        cache_expiry_hours: int = 24,  # 缓存过期时间（小时）
        lang: str = "zh",  # 语言：中文
        country: str = "cn"  # 国家：中国
    ):
        """
        初始化应用信息查询器

        Args:
            cache_dir: 缓存目录路径
            cache_expiry_hours: 缓存过期时间（小时）
            lang: 查询语言（zh=中文, en=英文）
            country: 查询国家（cn=中国, us=美国）
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.cache_expiry_hours = cache_expiry_hours
        self.lang = lang
        self.country = country

        self.cache_file = self.cache_dir / "app_info_cache.json"

        # 先初始化logger
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        # 再加载缓存（缓存加载需要使用logger）
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """加载缓存数据"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                self.logger.info(f"✅ 加载缓存: {len(cache_data)} 条记录")
                return cache_data
            except Exception as e:
                self.logger.warning(f"⚠️ 缓存加载失败: {e}")
                return {}
        return {}

    def _save_cache(self):
        """保存缓存数据"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            self.logger.info(f"💾 缓存已保存: {len(self.cache)} 条记录")
        except Exception as e:
            self.logger.error(f"❌ 缓存保存失败: {e}")

    def _is_cache_expired(self, cache_entry: Dict) -> bool:
        """检查缓存是否过期"""
        if 'timestamp' not in cache_entry:
            return True

        timestamp_str = cache_entry['timestamp']
        timestamp = datetime.fromisoformat(timestamp_str)
        expiry_time = timestamp + timedelta(hours=self.cache_expiry_hours)

        return datetime.now() > expiry_time

    def _extract_app_info(self, details: Dict) -> Dict[str, Any]:
        """
        从 Google Play API 返回的详细信息中提取关键字段

        Args:
            details: Google Play API 返回的完整应用信息

        Returns:
            提取后的应用信息字典（仅包含包名、名称、分类）
        """
        return {
            'packageName': details.get('appId', ''),
            'title': details.get('title', ''),
            'category': details.get('genre', '')
        }

    def fetch_app_info(self, package_name: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        查询单个应用信息

        Args:
            package_name: 应用包名（如 com.whatsapp）
            force_refresh: 是否强制刷新（跳过缓存）

        Returns:
            应用信息字典，查询失败返回 None
        """
        # 检查缓存
        if not force_refresh and package_name in self.cache:
            cache_entry = self.cache[package_name]
            if not self._is_cache_expired(cache_entry):
                self.logger.info(f"✅ 从缓存读取: {package_name}")
                return cache_entry['data']

        self.logger.info(f"🔍 正在查询: {package_name}")

        try:
            # 调用 Google Play API
            details = app(
                package_name,
                lang=self.lang,
                country=self.country
            )

            if not details:
                self.logger.warning(f"⚠️ 应用未找到: {package_name}")
                return None

            # 提取关键信息
            app_info = self._extract_app_info(details)

            # 更新缓存
            self.cache[package_name] = {
                'data': app_info,
                'timestamp': datetime.now().isoformat()
            }
            self._save_cache()

            self.logger.info(f"✅ 查询成功: {app_info['title']} ({package_name})")
            return app_info

        except Exception as e:
            self.logger.error(f"❌ 查询失败 {package_name}: {e}")
            return None

    def fetch_multiple_apps(self, package_names: List[str], delay: float = 1.0) -> Dict[str, Dict]:
        """
        批量查询应用信息

        Args:
            package_names: 包名列表
            delay: 每次查询之间的延迟（秒），避免被封禁

        Returns:
            包名到应用信息的映射字典
        """
        results = {}

        for i, package_name in enumerate(package_names, 1):
            self.logger.info(f"📦 进度: {i}/{len(package_names)}")

            app_info = self.fetch_app_info(package_name)
            if app_info:
                results[package_name] = app_info

            # 延迟，避免请求过快
            if i < len(package_names):
                time.sleep(delay)

        return results

    def search_by_keyword(self, keyword: str, num_results: int = 10) -> List[Dict]:
        """
        通过关键词搜索应用

        Args:
            keyword: 搜索关键词
            num_results: 返回结果数量

        Returns:
            搜索结果列表
        """
        self.logger.info(f"🔍 搜索关键词: {keyword}")

        try:
            results = search(
                keyword,
                lang=self.lang,
                country=self.country,
                num=num_results
            )

            self.logger.info(f"✅ 找到 {len(results)} 个结果")

            return results

        except Exception as e:
            self.logger.error(f"❌ 搜索失败: {e}")
            return []

    def export_to_txt(self, output_file: str = "./data/app_info.txt"):
        """
        将缓存的应用信息导出为文本文件

        Args:
            output_file: 输出文件路径
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        lines.append("=" * 80)
        lines.append("应用信息列表")
        lines.append(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"总计: {len(self.cache)} 个应用")
        lines.append("=" * 80)
        lines.append("")

        for package_name, cache_entry in sorted(self.cache.items()):
            app_info = cache_entry['data']

            lines.append(f"📦 包名: {app_info.get('packageName', 'N/A')}")
            lines.append(f"📱 名称: {app_info.get('title', 'N/A')}")
            lines.append(f"📂 分类: {app_info.get('category', 'N/A')}")
            lines.append("-" * 80)
            lines.append("")

        content = "\n".join(lines)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.logger.info(f"✅ 已导出到: {output_file}")

    def export_to_json(self, output_file: str = "./data/app_info.json"):
        """
        将缓存的应用信息导出为 JSON 文件

        Args:
            output_file: 输出文件路径
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 只导出应用数据，不包含时间戳
        export_data = {
            pkg: entry['data']
            for pkg, entry in self.cache.items()
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"✅ 已导出到: {output_file}")

    def get_summary(self) -> Dict:
        """获取缓存统计信息"""
        total = len(self.cache)
        categories = {}

        for cache_entry in self.cache.values():
            app_info = cache_entry['data']
            category = app_info.get('category', 'Unknown')
            categories[category] = categories.get(category, 0) + 1

        return {
            'total_apps': total,
            'categories': categories
        }


def main():
    """测试和示例代码"""
    # 初始化查询器
    fetcher = AppInfoFetcher(cache_dir="./data/app_info_cache")

    print("=" * 80)
    print("应用信息查询工具测试")
    print("=" * 80)

    # 示例1: 查询单个应用
    print("\n📦 测试1: 查询单个应用")
    print("-" * 80)
    app_info = fetcher.fetch_app_info("com.whatsapp")
    if app_info:
        print(f"应用名称: {app_info['title']}")
        print(f"开发者: {app_info['developer']}")
        print(f"分类: {app_info['category']}")
        print(f"评分: {app_info['score']}")
        print(f"下载量: {app_info['installs']}")

    # 示例2: 批量查询
    print("\n📦 测试2: 批量查询应用")
    print("-" * 80)
    package_names = [
        "com.whatsapp",
        "com.facebook.katana",
        "com.instagram.android",
        "com.tencent.mm",  # 微信
        "com.tencent.mobileqq",  # QQ
        "com.alibaba.android.rimet",  # 钉钉
        "com.ss.android.ugc.aweme",  # 抖音
        "com.smile.gifmaker",  # 快手
    ]
    results = fetcher.fetch_multiple_apps(package_names, delay=2.0)
    print(f"✅ 成功查询 {len(results)}/{len(package_names)} 个应用")

    # 示例3: 搜索应用
    print("\n🔍 测试3: 搜索关键词 '微信'")
    print("-" * 80)
    search_results = fetcher.search_by_keyword("微信", num_results=5)
    for i, app in enumerate(search_results, 1):
        print(f"{i}. {app.get('title')} - {app.get('appId')}")

    # 示例4: 导出文件
    print("\n💾 测试4: 导出文件")
    print("-" * 80)
    fetcher.export_to_txt("./data/app_list.txt")
    fetcher.export_to_json("./data/app_list.json")

    # 示例5: 统计信息
    print("\n📊 测试5: 统计信息")
    print("-" * 80)
    summary = fetcher.get_summary()
    print(f"总应用数: {summary['total_apps']}")
    print(f"\n分类统计:")
    for category, count in sorted(summary['categories'].items(), key=lambda x: x[1], reverse=True):
        print(f"  {category}: {count}")


if __name__ == "__main__":
    main()
