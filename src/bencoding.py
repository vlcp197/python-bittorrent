# Bencoding is a data serialization format used in torrent files
# for the Bittorrent protocol.
# Its a simple and efficient way to encode data in a platform-independent way.
# Bencoding suports four differents types of values:
# Strings, integers, lists and dictionaries.
# Exemple of a bencoded value: d4:name4:spam4:info12:length4:1234e .

from collections import OrderedDict

# Indicates start of integers
TOKEN_INTEGER = b'i'

# Indicates start of lists
TOKEN_LIST = b'l'

# Indicates start of dicts
TOKEN_DICT = b'd'

# Indicates end of lists, dicts and integer values
TOKEN_END = b'e'

# Delimits string length from string data
TOKEN_STRING_SEPARATOR = b':'


class Decoder:
    def __init__(self):
        ...


class Encoder:
    def __init__(self):
        ...