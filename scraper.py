import os
import re
import json
import hashlib
from collections import Counter
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup

os.makedirs('./files', exist_ok=True) # create directory for storing results
VISITED_PAGES_FILE = './files/pages_visited.txt'   # one URL per line (for unique pages + subdomains)
STATS_FILE = './files/stats.json'                  # word counts + longest page
FAILED_FILE = './files/failed_pages.txt' # pages that failed to be visited
HASH_FILE = './files/page_hashes.txt' # hashes of pages for duplicate checking
THRESHOLD_BITS = 62 # minimum number of similar bits required for pages to be considered duplicates

MAX_BYTES = 5 * 1024 * 1024    # skip files over 5 MB
MIN_WORDS = 50                 # pages with fewer words = low information
MAX_URL_LEN = 200              # very long URLs are usually traps
NUM_HASH_BITS = 64             # hashes for simhash are 64 bits

ALLOWED_SITES = ["ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu"] # stay within the specified domains

# regular expression for common web crawler traps
TRAP_REGEX = re.compile(
    r"(calendar|ical|\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|action=|do=|share=|replytocom|"
    r"login|logout|sessionid|/feed|/wp-json|\?.*(sort|filter|format)=)", re.I)

# stop words that are ignored on pages
STOP_WORDS = set("""a about above after again against all am an and any are aren't as at be because been before being below 
between both but by can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from further 
had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll 
i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off on once only or other 
ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the 
their theirs them themselves then there there's these they they'd they'll they're they've this those through to too under until 
up very was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which while who who's whom why 
why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves""".split())

def load_stats():
    '''
    Loads the stats from previous sessions.
    '''

    try:
        with open(STATS_FILE) as f:
            d = json.load(f)

        # return saved stats if valid file was found
        return Counter(d["words"]), d["longest"] 

    except (FileNotFoundError, ValueError):

        # return empty stats if file was not found or was invalid
        return Counter(), ["", 0]

def load_hashes():
    '''
    Loads all the hashes of previous pages
    '''

    try:
        with open(HASH_FILE) as f:

            # return hashes if file is found
            return [int(line) for line in f if line.strip()]

    except FileNotFoundError:

        # return no hashes if file was not found
        return []     

# initalize variables for previous data
word_counts, longest_page = load_stats()
pages_since_save = 0
page_hashes = load_hashes()

def save_stats():
    '''
    Saves the current word_counts and longest_page to the stats file
    '''

    with open(STATS_FILE, 'w') as f:
        json.dump({"words": word_counts, "longest": longest_page}, f)

def write_line_to_file(file_name, text):
    '''
    Appends the given text to the given file and then adds a new line at the end
    '''

    with open(file_name, 'a') as f:
        f.write(f'{text}\n')

def scraper(url, resp):
    '''
    Returns the next valid links for the given url and response
    '''

    links = extract_next_links(url, resp)

    return [link for link in links if is_valid(link)]

def extract_next_links(url, resp):
    '''
    Returns a list of the links from a given page and updates the report
    '''

    # refer to global in order to avoid UnboundLocalError
    global pages_since_save

    # is response is bad, add to list of failed files and return no links
    if resp.status != 200 or resp.raw_response is None or not resp.raw_response.content or resp.error is not None:
        write_line_to_file(FAILED_FILE, f'{url} status={resp.status} error={resp.error}')
        return []

    # get response content
    content = resp.raw_response.content

    # if file is beyond upper limit then return no links
    if len(content) > MAX_BYTES:
        return []

    # use the final URL (after redirects) without its fragment as the base for relative links
    base_url = urldefrag(resp.raw_response.url or url)[0]

    # parse the page content into separate parts
    soup = BeautifulSoup(content, "html.parser")

    # remove all script and style elements to prevent code and markup from being counted as ordinary text
    for tag in soup(["script", "style"]):
        tag.decompose()

    # extract and tokenize the words
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", soup.get_text(separator=" ").lower())

    # record this page as being found (for the report)
    write_line_to_file(VISITED_PAGES_FILE, base_url)

    # low-information / dead page: don't count its words or follow its links
    if len(words) < MIN_WORDS:
        return []

    # get all the words that aren't stop words or empty strings
    content_words = [w for w in words if w not in STOP_WORDS and len(w) > 1]

    # get the sim hash for the page contents
    page_hash = get_simhash(content_words)

    # duplicate page: don't count its words or follow its links
    if is_simhash_match(page_hash):
       return []
    
    # update stats for the report
    if len(words) > longest_page[1]:
        longest_page[0], longest_page[1] = base_url, len(words)

    # content_words as stop words are removed
    word_counts.update(content_words)

    # increment the pages since the last save
    pages_since_save += 1

    # once its been 10 pages since the last save, save the stats and restart the counter
    if pages_since_save >= 10:
        save_stats()
        pages_since_save = 0

    next_links = []

    # collect links: make absolute, remove fragment
    for anchor in soup.find_all('a', href=True):
        try:
            link = urldefrag(urljoin(base_url, anchor['href'].strip()))[0]
        except ValueError:      # malformed href (e.g. bad IPv6 bracket host)
            continue
        next_links.append(link)

    return next_links

def is_valid(url):
    '''
    Returns true if a URL is valid

    Checks url length, http/https, domain, common traps, and non-text file types.
    '''

    try:

        # check if the url is not ASCII or is too long
        if not url.isascii() or len(url) > MAX_URL_LEN:
            return False

        # check that the url is http or https
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False

        # url must be one of the 4 allowed domains (or a subdomain of them)
        host = (parsed.hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in ALLOWED_SITES):
            return False

        # check for common traps
        if TRAP_REGEX.search(parsed.path + "?" + parsed.query):
            return False

        # check if a url includes a repeating pattern of 3 or more times
        segments = [s for s in parsed.path.split("/") if s]
        if segments and max(Counter(segments).values()) >= 3:
            return False

        # skip non-text file types
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    except Exception as e:

        #if an error was encountered add it to the list of failed files
        write_line_to_file(FAILED_FILE, f'Invalid URL: {url}, Type: {e}')

        return False

def get_simhash(words):   
    '''
    Get the simhash of the page

    Collect words and hash them into 64bits. Sum each hash with weights
    to determine what the most common bit at a position was and have
    it accordingly in the simhash
    '''
    
    # get the word frequencies
    frequencies = compute_word_frequencies(words)

    # create a list of 0s for the number of hash bits
    bits = [0] * NUM_HASH_BITS

    # hash each word
    for word, frequency in frequencies.items():

        # get first 8 bytes of hash --> convert to int --> convert to 64 bits
        byte_hash = hashlib.sha256(word.encode('utf-8')).digest()[:8]
        int_hash = int.from_bytes(byte_hash, 'big')
        bit_hash = f'{int_hash:0{NUM_HASH_BITS}b}'

        # add if the bit is 1 and subtract if the bit is 0
        for i in range(NUM_HASH_BITS):
            bits[i] += (1 if bit_hash[i] == '1' else -1) * frequency
        
    # positive sum indices = 1, non-positive sum indices = 0
    return int(''.join('1' if bits[i] > 0 else '0' for i in range(NUM_HASH_BITS)), 2) # converted to base10 for XOR calcs

    
def compute_word_frequencies(tokens):
    '''
    Takes in a list of tokens and returns a dict of the 
    tokens and their frequencies.
    '''

    frequencies = {}

    # increment the frequency for each encounter of a token
    for token in tokens: 
        frequencies[token] = frequencies.get(token, 0) + 1

    return frequencies

def is_simhash_match(page_hash):
    '''
    Returns true if the given hashes are similar to other page's hashes

    Checks if ((# common bits) / (# total bits)) >= threshold
    Threshold for similarity is 62 bits in common, or roughly 97% similarity
    '''

    for other_hash_line in page_hashes:

        # Counting 0 bits from XOR = counting # bits in common
        hash_xor = page_hash ^ other_hash_line
        similarity = f'{hash_xor:0{NUM_HASH_BITS}b}'.count('0')

        # if similarity is past the threshold, indicate a match
        if similarity >= THRESHOLD_BITS:
            return True
    
    # store the hash
    write_line_to_file(HASH_FILE, page_hash)
    page_hashes.append(page_hash)

    # no matching hash was found
    return False
