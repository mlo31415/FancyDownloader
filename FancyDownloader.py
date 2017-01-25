# Program to download an entire wiki (except for history) from Wikidot and then to keep it synchronized.
# The wiki is downloaded to a directory.  Each wiki page generates two files and possibly a directory:
#     <page>.txt containing the source of the page
#     <page>.xml containing the metadata of the page
#     <page> a directory containing the attached files (created only if there are attached files)

# The basic scheme is to create a list of all pages in the wiki sorted from most-recently-updated to least-recently-updated.
# The downloader then walks the list, downloading new copies of each page which is newer on the wiki than in the local copy.
#    It stops when it finds a page where the local copy is up-to-date
#          (Note that this leave it vulnerable to a case where the downloader fails partway through and updates some pages and not others.
#          The next time it is run, if any pages have been updated in the mean time, the massed pages won;t be noticed.
#          Since the alternative is to check every page every time, and since this was written to deal with a wiki with >20K pages, it is an accepted issue to be dea;lt with by hand.)
#    The next step is to compare the list of all local .txt files with the list of all pages, and to download any which are missing.
#          (Note that this does not deal with deleted .xml files or deleted attached files.  This fairly cheap to check, so it might be a useful enhancement.)
#    The final step is to look for local .txt files which are not on the wiki.  These will typically be files which have been deleted on the wiki.  They are deleted locally.

# The wiki to be synched and the credentials are stoed in a file url.txt.  It contains a single line of text of the form:
#      https://fancyclopedia:rdS...80g@www.wikidot.com/xml-rpc-api.php
# where 'fancyclopedia' is the wiki and 'rdS...80g' is the access key

# The synched wiki will be put into a directory 'site' one level up from the Python code.

# It was developed in PyCharm2016


from xmlrpc import client
import xml.etree.ElementTree as ET
import os
import datetime
import base64
import time

def DecodeDatetime(dtstring):
    if dtstring == None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '")+dtstring+"'"
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')

# Download a page from Wikidot and possibly store it locally.
# The page's contents are stored in their files, the source in <saveName>.txt, the rendered HTML in <saveName>..html, and all of the page meta information in <saveName>.xml
# Setting skipIfNotNewer to True allows a forced downloading of the page, reghardless of whether it is already stored locally.  This is mostly useful to overwrite the hidden consequences of old sync errors
# The return value is True when the local version of the page has been updated, and False otherwise
def DownloadPage(localName, skipIfNotNewer):
    time.sleep(0.05)    # Wikidot has a limit on the number of RPC calls/second.  This is to throttle the dowload to stay on the safe side.

    # Download the page's data
    try:
        wikiName=localName.replace("_", ":", 1)  # The '_' is used in  place of Wikidot's ':' in page names in non-default namespaces. Convert back to the ":" form for downloading)
        if wikiName == "con-": # "con" is a special case since that is a reserved word in Windows and may not be used as a filename.  We use "con-" which is not a possible wiki name, for the local name .
            wikiName="con"
        pageData=client.ServerProxy(url).pages.get_one({"site" : "fancyclopedia", "page" : wikiName})
    except:
        print("****Failure downloading "+localName)
        return False # Its safest on download failure to return that nothing changed

    # NOTE: This relies on the update times stored in the local file's xml and in the wiki page's updated_at metadata
    # It will not detect incompletely downloaded pages if the xml file exists
    if skipIfNotNewer:
        # Get the updated time for the local version
        localUpdatedTime=None
        if os.path.isfile(localName+ ".xml"):
            tree=ET.parse(localName + ".xml")
            doc=tree.getroot()
            localUpdatedTime=doc.find("updated_at").text

        # Get the wiki page's updated time
        wikiUpdatedTime=GetPageWikiTime(localName, pageData)
        # We return True whenever we have just downloaded a page which was already up-to-date locally
        tWiki = DecodeDatetime(wikiUpdatedTime)
        tLocal = DecodeDatetime(localUpdatedTime)

        if tWiki <= tLocal:
            return False

    # OK, we're going to download this one
    print("   Updating: '" + localName + "'")

    # Write the page source to <localName>.txt
    if pageData.get("content", None) != None:
        with open(localName + ".txt", "wb") as file:
            file.write(pageData["content"].encode("utf8"))

    # Write the page's rendered HTML to <localName>.html
    if pageData.get("html", None) != None:
        with open(localName + ".html", "wb") as file:
            file.write(pageData["html"].encode("utf8"))

    # Write the rest of the page's data to <localName>.xml
    SaveMetadata(localName, pageData)

    # Check for attached files
    # If any exist, save them in a directory named <localName>
    # If none exist, don't create the directory
    # Note that this code does not delete the directory when previously-existing files have been deleted from the wiki page
    fileNameList=client.ServerProxy(url).files.select({"site": "fancyclopedia", "page": wikiName})
    if len(fileNameList) > 0:
        if not os.path.exists(localName):
            os.mkdir(localName)   # Create a directory for the files and metadata
            os.chmod(localName, 0o777)
        for fileName in fileNameList:
            try:
                fileStuff = client.ServerProxy(url).files.get_one({"site": "fancyclopedia", "page": wikiName, "file": fileName})    # Download the file's content and metadata
            except client.Fault:
                print("**** client.Fault loading "+fileName+". The file is probably too big.")
                continue
            path=os.path.join(os.getcwd(), localName, fileName)
            content=base64.b64decode(fileStuff["content"])
            with open(path, "wb+") as file:
                file.write(content)     # Save the content

            # Now the metadata
            del fileStuff["content"]    # We don't want to store the content in the metadata
            SaveMetadata(os.path.join(localName, fileName), fileStuff)


    return True

# Save the wiki page's metadata to an xml file
def SaveMetadata(localName, pageData):
    root = ET.Element("data")
    wikiUpdatedTime = None
    for itemName in pageData:
        if itemName == "content" or itemName == "html":  # Skip: We've already dealt with this
            continue
        # Page tags get handled specially
        if itemName == "tags":
            tags = pageData["tags"]
            if len(tags) > 0:
                tagsElement = ET.SubElement(root, "tags")
                for tag in tags:
                    tagElement = ET.SubElement(tagsElement, "tag")
                    tagElement.text = tag
            continue
        if itemName == "updated_at":  # Save the updated time
            wikiUpdatedTime = pageData[itemName]
        # For all other pieces of metadata, create a subelement in the xml
        if pageData[itemName] != None and pageData[itemName] != "None":
            element = ET.SubElement(root, itemName)
            element.text = str(pageData[itemName])

    # And write the xml out to file <localName>.xml.
    tree = ET.ElementTree(root)
    tree.write(localName + ".xml")
    return wikiUpdatedTime

# Get the wiki page's update time from the its metadata
def GetPageWikiTime(localName, pageData):
    for itemName in pageData:
        if itemName == "updated_at":  # Save the updated time
            return pageData[itemName]


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
# (We're using composition, here.)
print("Get list of all pages from Wikidot, sorted from most- to least-recently-updated")
listOfAllWikiPages=client.ServerProxy(url).pages.select({"site" : "fancyclopedia", "order": "updated_at desc"})
listOfAllWikiPages=[name.replace(":", "_", 1) for name in listOfAllWikiPages]   # ':' is used for non-standard namespaces on wiki. Replace the first ":" with "_" in all page names because ':' is invalid in Windows file names
listOfAllWikiPages=[name if name != "con" else "con-" for name in listOfAllWikiPages]   # Handle the "con" special case

# Download the recently updated pages until we start finding pages we already have the most recent version of
#
# stoppingCriterion controls how long the update runs
# stoppingCriterion:
#   >0 --> Run until we have encountered stoppingCriterion pages that don't need updates
#   =0 --> Run through all pages
# This is used to handle cases where the downloading and comparison process has been interrupted before updating all changed pages.
# In that case there is a wodge of up-to-date recently-changed pages before the pages that were past the interruption
stoppingCriterion=100
print("Downloading recently updated pages...")
countUpToDatePages=0
for pageName in listOfAllWikiPages:
    if not DownloadPage(pageName, True):
        countUpToDatePages+=1
        if stoppingCriterion > 0 and countUpToDatePages > stoppingCriterion:
            print("      Ending downloads. " + str(stoppingCriterion) + " up-to-date pages found")
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
    DownloadPage(pageName, True)

# And delete local copies of pages which have disappeared from the wiki
# Note that we don't detect and delete local copies of attached files which have been removed from the wiki where the wiki page remains.
print("Removing deleted pages...")
listOfAllDeletedPages = [val for val in listOfAllDirPages if val not in listOfAllWikiPages]  # Create a list of pages which exist locally, but not in the wiki
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

