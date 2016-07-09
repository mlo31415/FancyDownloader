#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET
import os
import datetime

def DecodeDatetime(dtstring):
    if dtstring == None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '")+dtstring+"'"
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')

# Download a page from Wikidot.
# The page's contents are stored in their files, the source in <pageName>.txt, the HTML in <pageName>..html, and all of the page information in <pageName>.xml
# The return value is True when the Wikidot version of the page is newer than the local version, and False otherwise
def DownloadPage(pageName):
    # Download the page's data
    api = client.ServerProxy(url)
    pageData=api.pages.get_one({"site" : "fancyclopedia", "page" : pageName})

    # Get the updated time for the local version
    localUpdatedTime=None
    if os.path.isfile(pageName+".xml"):
        tree=ET.parse(pageName+".xml")
        doc=tree.getroot()
        localUpdatedTime=doc.find("updated_at").text

    # Write the page source to <pageName>.txt
    if pageData.get("content", None) != None:
        with open(pageName + ".txt", "w") as file:
            file.write(pageData["content"])

    if pageData.get("html", None) != None:
        with open(pageName + ".html", "w") as file:
            file.write(pageData["html"])

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
        if itemName == "updated_at":    # Save the updated time
            wikiUpdatedTime=pageData[itemName]
        if pageData[itemName] != None and pageData[itemName] != "None":
            element=ET.SubElement(root, itemName)
            element.text=str(pageData[itemName])

        print(itemName + ": " + str(pageData[itemName]))

    # And write it out.
    tree=ET.ElementTree(root)
    tree.write(pageName+".xml")


    tWiki=DecodeDatetime(wikiUpdatedTime)
    tLocal=DecodeDatetime(localUpdatedTime)

    return tWiki>tLocal


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
# listOfRecentlyUpdatedPages=[ii for n,ii in enumerate(list) if ii not in list[:n]] # Remove duplicates

# Download the recently updated pages until we start finding pages we already have
for pageName in listOfRecentlyUpdatedPages:
    if not DownloadPage(pageName):
        break

# Now download missing pages
for pageName in listOfAllMissingPages:
    DownloadPage(pageName)

print("Done")

