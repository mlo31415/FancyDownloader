#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET
import os

def downloadPage(pageName):
    # Download the page's data
    api = client.ServerProxy(url)
    pageData=api.pages.get_one({"site" : "fancyclopedia", "page" : pageName})

    # Write the page source to <pageName>.txt
    if pageData.get("content", None) != None:
        with open(pageName + ".txt", "w") as file:
            print(pageData["content"], file=file)

    if pageData.get("html", None) != None:
        with open(pageName + ".html", "w") as file:
            print(pageData["html"], file=file)

    # Write the rest of the page's data to <pageName>.xml
    root=ET.Element("data")
    for itemName in pageData:
        if itemName == "content" or itemName == "html":   # We've already dealt with this
            continue
        if itemName == "tags":
            tags=pageData["tags"]
            if len(tags) > 0:
                tagsElement=ET.SubElement(root, "tags")
                for tag in tags:
                    tagElement=ET.SubElement(tagsElement, "tag")
                    tagElement.text=tag
            continue
        if pageData[itemName] != None and pageData[itemName] != "None":
            element=ET.SubElement(root, itemName)
            element.text=str(pageData[itemName])

        print(itemName + ": " + str(pageData[itemName]))

    # And write it out.
    tree=ET.ElementTree(root)
    tree.write(pageName+".xml")

# ---------------------------------------------
# Main

# Get the magic URL for api access
url=open("url.txt").read()

# Change the working directory to the destination of the downloaded wiki
cwd=os.getcwd()
os.chdir(cwd+'/site')

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

# Get the page list from the wiki and sort it
api = client.ServerProxy(url)
listOfAllWikiPages=api.pages.select({"site" : "fancyclopedia"})
listOfAllWikiPages.sort()

# Get the page list from the downloaded directory and use that to create lists of missing pages and deleted pages
list=os.listdir(".")
listOfAllDirPages=[]
for p in list:
    if p.endswith(".txt"):
        listOfAllDirPages.append(p[:-4])    # Since all pages have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)

listOfAllMissingPages = [val for val in listOfAllWikiPages if val not in listOfAllDirPages] # Create a list of pages which are in the wiki and not downloaded
listOfAllDeletedPages = [val for val in listOfAllDirPages if val not in listOfAllWikiPages] # Create a list of pages which are dowloaded but not in the wiki

# Now, get as much as possible of the list of recently modified pages.
api = client.ServerProxy(url)
listOfRecentlyUpdatedPages=api.pages.select({"site" : "fancyclopedia", "order": "updated_at desc"})
# listOfRecentlyUpdatedPages=[ii for n,ii in enumerate(list) if ii not in list[:n]] # REmove duplicates

# Download the pages
for pageName in listOfAllWikiPages:
    downloadPage(pageName)

print("Done")

