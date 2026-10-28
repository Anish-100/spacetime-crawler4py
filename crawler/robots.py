import time
import xml.etree.ElementTree as ET
from threading import RLock
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from utils.download import download


class RobotsCache(object):
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.parsers = dict()   # "scheme://netloc" -> RobotFileParser
        self.lock = RLock()

    def get(self, url):
        '''
        Returns (parser, is_new_host) for the url's host.

        Fetches robots.txt through the cache server the first time a host is seen.
        If the host has no robots.txt (or it can't be fetched), everything is allowed.
        '''
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}"
        with self.lock:
            if key in self.parsers:
                return self.parsers[key], False

            rp = RobotFileParser(f"{key}/robots.txt")
            try:
                resp = download(rp.url, self.config, self.logger)
            except Exception as e:
                self.logger.warning(f"robots.txt fetch failed for {key}: {e}")
                resp = None

            if resp is not None and resp.status == 200 and resp.raw_response is not None:
                rp.parse(resp.raw_response.text.splitlines())
                self.logger.info(f"Using robots.txt for {key}")
            else:
                rp.allow_all = True     # no robots.txt -> crawl as normal

            self.parsers[key] = rp
            time.sleep(self.config.time_delay)  # the robots fetch is a request to this host too
            return rp, True


def is_sitemap(resp):
    '''
    Returns true if the response is an XML sitemap or sitemap index.
    '''
    if resp.status != 200 or resp.raw_response is None or not resp.raw_response.content:
        return False
    head = resp.raw_response.content[:1000] # First 1k bytes
    return b"<urlset" in head or b"<sitemapindex" in head


def parse_sitemap(resp):
    '''
    Returns every <loc> url in a sitemap or sitemap index.
    '''
    try:
        root = ET.fromstring(resp.raw_response.content)
    except ET.ParseError:
        return []
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
