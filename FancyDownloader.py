#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET



# Write a default position file if nothing exists
try:
    file=open("FancyDownloaderState.xml")
    file.close()
except:
    root=ET.Element("root")
    position=ET.SubElement(root, "Position")
    position.text="FAPA"
    tree=ET.ElementTree(root)
    tree.write("FancyDownloaderState.xml")

# Open the site
url=open("url.txt").read()
api = client.ServerProxy(url)

# Get the page list and sort it
listOfAllPages=api.pages.select({"site" : "fancyclopedia"})
listOfAllPages.sort()

for pageName in listOfAllPages:
    api = client.ServerProxy(url)
    p=api.pages.get_one({"site" : "fancyclopedia", "page" : "_default:"+pageName})
    print(p)

print("Done")

