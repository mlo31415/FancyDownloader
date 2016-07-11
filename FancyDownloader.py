#!/usr/bin/python

import sys
from optparse import OptionParser
from xmlrpc import client
from tkinter import filedialog
import xml.etree.ElementTree as ET
import os
import datetime
import base64

def DecodeDatetime(dtstring):
    if dtstring == None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '")+dtstring+"'"
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')

# Download a page from Wikidot.
# The page's contents are stored in their files, the source in <saveName>.txt, the HTML in <saveName>..html, and all of the page information in <saveName>.xml
# The return value is True when the Wikidot version of the page is newer than the local version, and False otherwise
def DownloadPage(localName):

    # Download the page's data
    print("   Downloading: '" + localName + "'")
    wikiName=localName.replace("_", ":", 1)  # Convert back to the ":" form for downloading)
    if wikiName == "con-": # "con" is a special case since that is a reserved word in Windoes and may not be used as a filename.  We use "con-" which is not a possible wiki name, for the local name .
        wikiName="con"
    pageData=client.ServerProxy(url).pages.get_one({"site" : "fancyclopedia", "page" : wikiName})

    # Get the updated time for the local version
    localUpdatedTime=None
    if os.path.isfile(localName+ ".xml"):
        tree=ET.parse(localName + ".xml")
        doc=tree.getroot()
        localUpdatedTime=doc.find("updated_at").text

    # Write the page source to <saveName>.txt
    if pageData.get("content", None) != None:
        with open(localName + ".txt", "wb") as file:
            file.write(pageData["content"].encode("utf8"))

    if pageData.get("html", None) != None:
        with open(localName + ".html", "wb") as file:
            file.write(pageData["html"].encode("utf8"))

    # Write the rest of the page's data to <saveName>.xml
    wikiUpdatedTime = SaveMetadata(localName, pageData)

    # Check for attached files
    fileNameList=client.ServerProxy(url).files.select({"site": "fancyclopedia", "page": wikiName})
    if len(fileNameList) > 0:
        if not os.path.exists(localName):
            os.mkdir(localName)   # Create a directory for the files and metadata
            os.chmod(localName, 0o777)
        for fileName in fileNameList:
            fileStuff = client.ServerProxy(url).files.get_one({"site": "fancyclopedia", "page": wikiName, "file": fileName})    # Download the file's content and metadata
            path=os.path.join(os.getcwd(), localName, fileName)
            content=base64.b64decode(fileStuff["content"])
            with open(path, "wb+") as file:
                file.write(content)     # Save the content

            # Now the metadata
            del fileStuff["content"]    # We don't want to store the content in the metadata
            SaveMetadata(os.path.join(localName, fileName), fileStuff)

    # We return True whenever we have just downloaded a page which was already up-to-date locally
    tWiki=DecodeDatetime(wikiUpdatedTime)
    tLocal=DecodeDatetime(localUpdatedTime)

    return tWiki>tLocal


def SaveMetadata(localName, pageData):
    root = ET.Element("data")
    for itemName in pageData:
        if itemName == "content" or itemName == "html":  # We've already dealt with this
            continue
        if itemName == "tags":
            tags = pageData["tags"]
            if len(tags) > 0:
                tagsElement = ET.SubElement(root, "tags")
                for tag in tags:
                    tagElement = ET.SubElement(tagsElement, "tag")
                    tagElement.text = tag
            continue
        wikiUpdatedTime=None
        if itemName == "updated_at":  # Save the updated time
            wikiUpdatedTime = pageData[itemName]
        if pageData[itemName] != None and pageData[itemName] != "None":
            element = ET.SubElement(root, itemName)
            element.text = str(pageData[itemName])

    # And write it out.
    tree = ET.ElementTree(root)
    tree.write(localName + ".xml")
    return wikiUpdatedTime

# ---------------------------------------------
# Main

# Get the magic URL for api access
url=open("url.txt").read()

# Change the working directory to the destination of the downloaded wiki
cwd=os.getcwd()
path=os.path.join(cwd, "..\\site")
os.chdir(path)
os.chmod(path, 0o777)

# Now, get list of recently modified pages.  It will be ordered from most-recently-updated to least.
print("Get list of all pages from Wikidot, sorted from most- to least-recently-updated")
listOfAllWikiPages=client.ServerProxy(url).pages.select({"site" : "fancyclopedia", "order": "updated_at desc"})
listOfAllWikiPages=[name.replace(":", "_", 1) for name in listOfAllWikiPages]   # replace the first ":" with "_" in all page names
listOfAllWikiPages=[name if name != "con" else "con-" for name in listOfAllWikiPages]   # Handle the "con" special case

# Download the recently updated pages until we start finding pages we already have
print("Downloading recently updated pages...")
for pageName in listOfAllWikiPages:
    if not DownloadPage(pageName):  # Quit as soon as we start re-loading pages which have not been updated
        print("      Page is up-to-date. Ending downloads")
        break

# Get the page list from the local directory and use that to create lists of missing pages and deleted pages
print("Creating list of local files")
list = os.listdir(".")
# Since all local copies of pages have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)
# So we want a list of just those names stripped of the extension
listOfAllDirPages=[p[:-4] for p in list if p.endswith(".txt")]

# Now figure out what pages are missing and download them.
print("Downloading missing pages...")
listOfAllMissingPages = [val for val in listOfAllWikiPages if val not in listOfAllDirPages]  # Create a list of pages which are in the wiki and not downloaded
if len(listOfAllMissingPages) == 0:
    print("   There are no missing pages")
for pageName in listOfAllMissingPages:
    DownloadPage(pageName)

# And delete local copies of pages which have disappeared from the wiki
print("Removing deleted pages...")
listOfAllDeletedPages = [val for val in listOfAllDirPages if val not in listOfAllWikiPages]  # Create a list of pages which are dowloaded but not in the wiki
if len(listOfAllDeletedPages) == 0:
    print("   There are no pages to delete")
for pageName in listOfAllDeletedPages:
    print("   Removing: " + pageName)
    if os.path.isfile(pageName + ".xml"):
        os.remove(pageName + ".xml")
    if os.path.isfile(pageName + ".html"):
        os.remove(pageName + ".html")
    if os.path.isfile(pageName + ".txt"):
        os.remove(pageName + ".txt")

print("Done")

