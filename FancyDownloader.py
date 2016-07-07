#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml

# Open the site

url=open("url.txt").read()
api = client.ServerProxy(url)


# Get the page list and sort it
retry=True
while retry:
    try:
        pages=api.pages.select({"site" : "fancyclopedia"})
        retry=False
    except:
        retry=True

pages.sort()

text=open("FancyDownloaderState.xml").read()

fullname=api.page_exists("fapa")
categories=api.get_categories()
name=api.get_username()


print("Done")

