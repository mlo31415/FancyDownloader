#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET
import os



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

os.chdir('site')

for pageName in listOfAllPages:
    api = client.ServerProxy(url)
    pageData=api.pages.get_one({"site" : "fancyclopedia", "page" : pageName})
    if pageData.get("content", None) != None:
        with open(pageName + ".txt", "w") as file:
            print(pageData["content"], file=file)

    print(pageData)

print("Done")

