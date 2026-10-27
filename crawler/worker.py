from threading import Thread

from inspect import getsource
from utils.download import download
from utils import get_logger
from crawler.robots import is_sitemap, parse_sitemap
import scraper
import time


class Worker(Thread):
    def __init__(self, worker_id, config, frontier):
        self.logger = get_logger(f"Worker-{worker_id}", "Worker")
        self.config = config
        self.frontier = frontier
        # basic check for requests in scraper
        assert {getsource(scraper).find(req) for req in {"from requests import", "import requests"}} == {-1}, "Do not use requests in scraper.py"
        assert {getsource(scraper).find(req) for req in {"from urllib.request import", "import urllib.request"}} == {-1}, "Do not use urllib.request in scraper.py"
        super().__init__(daemon=True)
        
    def run(self):
        while True:
            tbd_url = self.frontier.get_tbd_url()
            if not tbd_url:
                self.logger.info("Frontier is empty. Stopping Crawler.")
                break

            # robots.txt: queue the host's sitemaps once, skip disallowed urls
            robots, new_host = self.frontier.robots.get(tbd_url)
            if new_host:
                for sitemap in robots.site_maps() or []:
                    if scraper._is_valid(sitemap):
                        self.frontier.add_url(sitemap)
            if not robots.can_fetch(self.config.user_agent, tbd_url):
                self.logger.info(f"Blocked by robots.txt: {tbd_url}")
                self.frontier.mark_url_complete(tbd_url)
                continue

            resp = self.download_with_retry(tbd_url)
            if resp is None:
                self.logger.error(f"Giving up on {tbd_url}")
                self.frontier.mark_url_complete(tbd_url)
                raise ConnectionError(f"Giving up on {tbd_url}")
            self.logger.info(
                f"Downloaded {tbd_url}, status <{resp.status}>, "
                f"using cache {self.config.cache_server}.")
            if is_sitemap(resp):
                # sitemaps only feed the frontier, they don't count as pages
                scraped_urls = [u for u in parse_sitemap(resp) if scraper._is_valid(u)]
            else:
                scraped_urls = scraper.scraper(tbd_url, resp)
            for scraped_url in scraped_urls:
                self.frontier.add_url(scraped_url)
            self.frontier.mark_url_complete(tbd_url)
            delay = robots.crawl_delay(self.config.user_agent) or 0
            # Choose between robot delay and default delay.
            time.sleep(max(self.config.time_delay, delay))

    def download_with_retry(self, url, attempts=15):
        for i in range(attempts):
            try:
                return download(url, self.config, self.logger)
            except (ConnectionError, TimeoutError) as e:
                self.logger.warning(f"{url}: {e} (attempt {i+1}/{attempts})")
                if i < attempts - 1:
                    time.sleep(min(2 ** i, 20))  # 1s, 2s, 4s, 8s... capped at 20s
        return None

