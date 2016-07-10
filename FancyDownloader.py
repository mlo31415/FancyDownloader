#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET
import os
import datetime
import WikidotHelpers

def DecodeDatetime(dtstring):
    if dtstring == None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '")+dtstring+"'"
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')

# Download a page from Wikidot.
# The page's contents are stored in their files, the source in <saveName>.txt, the HTML in <saveName>..html, and all of the page information in <saveName>.xml
# The return value is True when the Wikidot version of the page is newer than the local version, and False otherwise
def DownloadPage(saveName):

    # Download the page's data
    print("   Downloading: '"+saveName+"'")
    pageData=client.ServerProxy(url).pages.get_one({"site" : "fancyclopedia", "page" : saveName.replace("_", ":", 1)})  # Convert back to the ":" form for downloading)

    # Get the updated time for the local version
    localUpdatedTime=None
    if os.path.isfile(saveName+".xml"):
        tree=ET.parse(saveName+".xml")
        doc=tree.getroot()
        localUpdatedTime=doc.find("updated_at").text

    # Write the page source to <saveName>.txt
    if pageData.get("content", None) != None:
        with open(saveName + ".txt", "wb") as file:
            file.write(pageData["content"].encode("utf8"))

    if pageData.get("html", None) != None:
        with open(saveName + ".html", "wb") as file:
            file.write(pageData["html"].encode("utf8"))

    # Write the rest of the page's data to <saveName>.xml
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

        # print(itemName + ": " + str(pageData[itemName]))

    # And write it out.
    tree=ET.ElementTree(root)
    tree.write(saveName+".xml")


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

# Now, get list of recently modified pages.  It will be ordered from most-recently-updated to least.
listOfAllWikiPages=client.ServerProxy(url).pages.select({"site" : "fancyclopedia", "order": "updated_at desc"})
listOfAllWikiPages=[name.replace(":", "_", 1) for name in listOfAllWikiPages]   # replace the first ":" with "_" in all page names

# Download the recently updated pages until we start finding pages we already have
print("Downloading recently updated pages...")
for pageName in listOfAllWikiPages:
    if not DownloadPage(pageName):  # Quit as soon as we start re-loading pages which have not been updated
        break

# Get the page list from the local directory and use that to create lists of missing pages and deleted pages
print("Creating list of local files")
list = os.listdir(".")
# Since all local copies of pages have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)
# So we want a list of just those names stripped on extension
listOfAllDirPages=[p[:-4] for p in list if p.endswith(".txt")]

# Now figure out what pages are missing and download them.
print("Downloading missing pages...")
listOfAllMissingPages = [val for val in listOfAllWikiPages if val not in listOfAllDirPages]  # Create a list of pages which are in the wiki and not downloaded
for pageName in listOfAllMissingPages:
    DownloadPage(pageName)

# And delete local copies of pages which have disappeared from the wiki
print("Removing deleted pages...")
listOfAllDeletedPages = [val for val in listOfAllDirPages if val not in listOfAllWikiPages]  # Create a list of pages which are dowloaded but not in the wiki
for pageName in listOfAllDeletedPages:
    print("   Removing: " + pageName)
    if os.path.isfile(pageName + ".xml"):
        os.remove(pageName + ".xml")
    if os.path.isfile(pageName + ".html"):
        os.remove(pageName + ".html")
    if os.path.isfile(pageName + ".txt"):
        os.remove(pageName + ".txt")

print("Done")

