import hashlib
from collections import Counter

NUM_HASH_BITS = 64             # hashes for simhash are 64 bits
def get_simhash(words):   
    '''
    Get the simhash of the page.

    Collect words and hash them into 64bits. Sum each hash with weights
    to determine what the most common bit at a position was and have
    it accordingly in the simhash
    '''
    
    frequencies = Counter(words)

    bits = [0] * NUM_HASH_BITS
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


def is_simhash_match(page_hash,page_hashes):
    '''
    Returns true if the given hashes are similar to other page's hashes.

    Checks if ((# common bits) / (# total bits)) >= threshold
    Threshold for similarity is 62 bits in common, or roughly 97% similarity.
    '''
    THRESHOLD_BITS = 62
    for other_hash_line in page_hashes:
        # Counting 0 bits from XOR = counting # bits in common
        hash_xor = page_hash ^ other_hash_line
        similarity = f'{hash_xor:0{NUM_HASH_BITS}b}'.count('0')
        if similarity >= THRESHOLD_BITS:
            return True
    return False
