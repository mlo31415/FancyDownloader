#
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

import pywikibot
import xml.etree.ElementTree as ET
import os
import datetime
from datetime import timedelta
from typing import Optional, Tuple

from Log import Log, LogOpen
from HelpersPackage import WikiPagenameToWindowsFilename, WindowsFilenameToWikiPagename

#-----------------------------------------
# Find text bracketed by <b>...</b>
# Input is of the form <b stuff>stuff</b>stuff
# Return the contents of the first pair of brackets found, the remainder of the input string up to </b>, and anything leftover afterwards (the three stuffs)
def FindBracketedText(s: str, b: str) -> Optional[Tuple[str, str,str]]:
    strlower=s.lower()
    # Find <b ...>
    l1=strlower.find("<"+b.lower()) # Look for <b
    if l1 == -1:
        return "", "", s
    l2=strlower.find(">", l1)       # Look for following >
    if l2 == -1:
        Log("***Error: no terminating '>' found in "+strlower+"'", isError=True)
        return None
    s1=s[l1+len(b)+2:l2]

    # Find text between <b ...> and </b>
    l3=strlower.find("</"+b.lower()+">", l2+1)
    if l3 == -1:
        return None

    return s1, s[l2+len(b):l3], s[l3+len(b)+3:]


#-------------------------------------
# Function to pull an href and accompanying text from a Tag
# The structure is "<a href='URL'>LINKTEXT</a>
# We want to extract the URL and LINKTEXT
def GetHrefAndTextFromString(s: str) -> Tuple[Optional[str], Optional[str]]:
    s=FindBracketedText(s, "a")
    if s[0] == "":
        return None, None

    # Remove the 'href="' from trailing '"' from the string
    return s[0][6:-1], s[1]


def DecodeDatetime(dtstring: str) -> datetime:
    if dtstring is None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '"+dtstring+"'")
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')


# Download a page from Wikidot and possibly store it locally.
# The page's contents are stored in their files, the source in <saveName>.txt, the rendered HTML in <saveName>..html, and all of the page meta information in <saveName>.xml
# Setting pageData to None forces downloading of the page, reghardless of whether it is already stored locally.  This is mostly useful to overwrite the hidden consequences of old sync errors
# The return value is True when the local version of the page has been updated, and False otherwise
def DownloadPage(fancy, pageName: str, pageData: Optional[dict]) -> bool:
    pname=WikiPagenameToWindowsFilename(pageName)   # Get the windows filesystem compatible versions of the pagename

    # If we set updateAll to True, then we skip the date checks and always do the update
    action="Downloading"
    if pageData is not None:
        action="Updating"
        # NOTE: This relies on the update times stored in the local file's xml and in the last update time data from pageData
        # It will not detect incompletely downloaded pages if the xml file exists
        # Check the timestamps and only update if the page on the server is newer than the local copy

        # Get the updated time for the local version
        if os.path.isfile(pname+".xml"):
            # If no xml file exists, we want to do the download, since the local copy is missing or incomplete
            tree=ET.parse(pname+".xml")
            doc=tree.getroot()
            localTimestamp=doc.find("timestamp").text

            # Get the wiki page's updated time
            wikiTimestamp=pageData["timestamp"]

            # We return True whenever we have just downloaded a page which was already up-to-date locally
            if wikiTimestamp <= localTimestamp:
                return False

    # OK, we're going to download this one
    if pageName == pname:
        Log("   "+action+": '"+pageName+"'")
    else:
        Log("   "+action+": '"+pageName+"' as '"+pname+"'")

    page=pywikibot.Page(fancy, pageName)
    if page.text is None or len(page.text) == 0:
        Log("       empty page: "+pageName)

    # Write the page source to <pageName>.txt
    text=page.text
    if text is not None:
        with open(pname+".txt", "wb") as file:
            file.write(text.encode("utf8"))
    else:
        # If there's no text, delete any existing txt file
        if os.path.exists(pname+".txt"):
            os.remove(pname+".txt")

    # Write the page's metadata to <pageName>.xml
    SaveMetadata(pname+".xml", page)

    # Is this a file?
    if page.is_filepage():
        # Then download it.
        filename=pageName.split(":")
        assert len(filename) == 2
        pywikibot.FilePage(fancy, filename[1]).download(filename[1])
        Log("       "+filename[1]+" downloaded")

    return True


# Save the wiki page's metadata to an xml file
def SaveMetadata(localName: str, pageData: pywikibot.page) -> None:
    root = ET.Element("data")

    ET.SubElement(root, "title").text=str(pageData.title())
    ET.SubElement(root, "filename").text=str(pageData.title(as_filename=True))
    ET.SubElement(root, "urlname").text=str(pageData.title(as_url=True))
    ET.SubElement(root, "isRedirectPage").text=str(pageData.isRedirectPage())
    ET.SubElement(root, "numrevisions").text=str(len(pageData._revisions))
    ET.SubElement(root, "pageid").text=str(pageData.pageid)
    ET.SubElement(root, "revid").text=str(pageData._revid)
    ET.SubElement(root, "edittime").text=str(pageData.editTime())
    ET.SubElement(root, "permalink").text=str(pageData.permalink())

    ET.SubElement(root, "categories").text=str([c for c in pageData.categories()])
    #ET.SubElement(root, "backlinks").text=str([c for c in pageData.backlinks()])
    #ET.SubElement(root, "linkedPages").text=str([c for c in pageData.linkedPages()])

    ET.SubElement(root, "timestamp").text=str(pageData.latest_revision.timestamp)
    ET.SubElement(root, "user").text=str(pageData.latest_revision.user)

    # And write the xml out to file <localName>.xml.
    tree = ET.ElementTree(root)
    tree.write(localName)


# ############################################################################################
# ###################################  Main  #################################################
# ############################################################################################

# This opens the site specified by user-config.py with the credential in user-password.py.
fancy=pywikibot.Site()

# Change the working directory to the destination of the downloaded wiki
cwd=os.getcwd()
path=os.path.join(cwd, "..\\site")
os.chdir(path)
os.chmod(path, 0o777)
del path

LogOpen("Log", "Error", dated=True)

# Look for a file called "override.txt" -- if it exists, load those pages and do nothing else.
# Override.txt contains a list of page names, one name per line.
# if os.path.exists("../FancyDownloader/override.txt"):
#     with open("../FancyDownloader/override.txt", "r") as file:
#         override=file.readlines()
#     override=[x.strip() for x in override]  # Remove trailing '\n'
#     # Remove duplicates;
#     nodupes=[]
#     for x in override:
#         if x not in nodupes:
#             nodupes.append(x)
#     override=nodupes
#     del nodupes, x
#     Log("Downloading override pages...")
#     countDownloadedPages=0
#     for pageName in override:
#         if DownloadPage(fancy, pageName, None):
#             countDownloadedPages+=1
#     exit()

# Get list of pages on the wiki
# The strategy will be to first get a list of *all* updates sorted by date of last modification
# We'll then get rid of all but the most recent modification of each page.
# Note that we're using the recentchanges() call because the allpages() call doesn't return date of update.
# Note also that this list will contain pages that have been *deleted* on the wiki
Log("Download list of all pages from the wiki")
wikiPnames=[]
for ns in fancy.namespaces:
    if ns < 0:
        continue
    for page in fancy.allpages(namespace=ns):
        # Split on the first colon into namespace and page name
        sv=str(page).strip("[]")     # Drop leading and trailing square brackets
        assert sv.find(":") > 0
        parts=sv.split(":", 1)
        wikiPnames.append(parts[1])
Log("   Number of pages on wiki: "+str(len(wikiPnames)))

Log("Download list of recent pages (those updated in the last 90 days), sorted from most- to least-recently-updated")
current_time = fancy.server_time()
iterator=fancy.recentchanges(start = current_time, end=current_time - timedelta(hours=600000))   # Not for all time, just for the last 3 months...
recentWikiPages=[]
for v in iterator:
    recentWikiPages.append(v)

Log("   Downloaded list of changes includes "+str(len(recentWikiPages))+" items")

#allWikiPages=[val for val in allWikiPages if val["title"] == "Third Foundation"]

# Get rid of the older instances of each page.
# Use a dictionary which only contains the latest version
tempDict={}
for p in recentWikiPages:
    pname=p["title"]
    if pname in tempDict.keys():
        if p["timestamp"] > tempDict[pname]["timestamp"]:
            tempDict[pname]=p
    else:
        tempDict[pname]=p

# Recreate the listOfAllWikiPages from the de-duped dictionary
recentWikiPages=list(tempDict.values())

# Some members of this list are wiki pages referred to in the wiki which have not been created.
emptyWikiPnames=[val for val in recentWikiPages if val["newlen"] == 0]
Log("   After de-duping, there are "+str(len(recentWikiPages))+" pages left")

# Sort the list of all pages by timestamp
def sorttime(page):
    return page["timestamp"]
recentWikiPages=sorted(recentWikiPages, key=sorttime, reverse=True)
Log("   The oldest page change listed is "+str(recentWikiPages[-1]["timestamp"]))

# This list includes pages which are referred to in the wiki, but which have not been created yet.  We don't want them.
uncreatedWikiPnames=[val["title"] for val in recentWikiPages if val["oldlen"] == 0 and val["newlen"] == 0]
Log("   There are "+str(len(uncreatedWikiPnames))+" recent pages which are referenced on the wiki, but have not yet been created there. They will be ignored")
recentWikiPnames=[val["title"] for val in recentWikiPages]
createdWikiPnamesSet=set(recentWikiPnames)-set(uncreatedWikiPnames)
createdWikiPnames=list(createdWikiPnamesSet)
Log("   There are "+str(len(createdWikiPnames))+" recent pages that exist on the wiki")

# Get the list of pages from the local copy of the wiki and use that to create lists of missing pages and deleted pages
Log("Creating list of local files")
# Since all local copies of pages must have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)
# So we want a list of just those names stripped of the extension
# We also have to back-convert the filenames to get rid of the ;xxxx; that we used to replace certain special characters.
localFnamesTxt=[p[:-4] for p in os.listdir(".") if p.endswith(".txt")]
localFnamesXml=[p[:-4] for p in os.listdir(".") if p.endswith(".xml")]

# Create a list of all file names that have *both* .txt and .xml files
localFnames=list(set(localFnamesTxt) & set(localFnamesXml))  # Union of set of names of xml files and set of names of txt files yields all pages, partial and complete
Log("    There are "+str(len(localFnames))+ " pages which are in the local copy")

# Create a list of all file names that have one or the other but not both.
partialLocalFnames=list(set(localFnamesTxt) ^ set(localFnamesXml))       # Symmetric difference yields list of partial local copies of pages
partialLocalFnames=[p for p in partialLocalFnames if not p.startswith("Log 202")]   # Ignore log files that find there way here
if len(partialLocalFnames) == 0:
    Log("    There are no partial page downloads")
else:
    Log("    There are "+str(len(partialLocalFnames))+" partial page downloads")
    for pname in partialLocalFnames:
        DownloadPage(fancy, pname, None)


# Figure out what pages are missing from the local copy and download them.
# We do this because we may have at some point failed to make a local copy of a new page.  If it's never updated, it'll never be picked up by the recent changes code.
localPnamesSet=set([WindowsFilenameToWikiPagename(val) for val in localFnames])
wikiPnamesSet=set(wikiPnames)
missingLocalPnames=list(wikiPnamesSet-localPnamesSet)
Log("There are "+str(len(missingLocalPnames))+" pages which are on the wiki but not in the local copy.")

#TODO: Really ought to take into account changes with "logtype" == delete, as those are deletions, not updates
deletedWikiPnames=list(localPnamesSet-wikiPnamesSet)
Log("There are "+str(len(deletedWikiPnames))+ " pages which are in the local copy, but not on the wiki.")

# Download pages which exist in the website but not in the disk copy
Log("Downloading missing pages...")
countMissingPages=0
countStillMissingPages=0
if len(missingLocalPnames) == 0:
    Log("   There are no missing pages")
else:
    for pname in missingLocalPnames:
        if DownloadPage(fancy, pname, None):
            countMissingPages+=1
        else:
            countStillMissingPages+=1
Log("   "+str(countMissingPages)+" missing pages downloaded     "+str(countStillMissingPages)+" could not be downloaded")

# Download the recently updated pages until we start finding pages we already have the most recent version of
#
# stoppingCriterion controls how long the update runs
# stoppingCriterion:
#   >0 --> Run until we have encountered stoppingCriterion consecutive pages that don't need updates
#   =0 --> Run through all pages (this is slow and resource-intensive)
# This is used to handle cases where the downloading and comparison process has been interrupted before updating all changed pages.
# In that case there will be a wodge of up-to-date recently-changed pages before the pages that were past the interruption.
# StoppingCriterion needs to be big enough to get past that wodge.
stoppingCriterion=500
Log("Downloading recently updated pages...")
countUpToDatePages=0
countDownloadedPages=0
for page in recentWikiPages:
    pageName=page["title"]
    if pageName in createdWikiPnamesSet:
        if DownloadPage(fancy, pageName, page):
            countDownloadedPages+=1
        else:
            countUpToDatePages+=1
            if stoppingCriterion > 0 and countUpToDatePages > stoppingCriterion:
                Log("      "+str(countDownloadedPages)+" pages downloaded")
                Log("      Ending downloads. " + str(stoppingCriterion) + " up-to-date pages found")
                break

# Optionally, force the download of pages

forcedWikiDownloads=[]
#forcedWikiDownloads=[x for x in wikiPnames if "a" in x or "e" in x or "i" in x or "o" in x or "u" in x ]
if len(forcedWikiDownloads) > 0:
    Log("Forced downloading of pages...")
    countForcedPages=0
    countStillMissingPages=0
    forcedLocalPnames=[x for x in forcedWikiDownloads]
    for pname in forcedLocalPnames:
        if DownloadPage(fancy, pname, None):
            countForcedPages+=1
        else:
            countStillMissingPages+=1
    Log("   "+str(countForcedPages)+" forced pages downloaded     "+str(countStillMissingPages)+" could not be downloaded")


# And delete local copies of pages which have disappeared from the wiki
# Note that we don't detect and delete local copies of attached files which have been removed from the wiki where the wiki page remains.
Log("Removing deleted pages...")
countOfDeletedPages=0
countOfUndeletedPages=0
if len(deletedWikiPnames) == 0:
    Log("   There are no pages to delete")
for pname in deletedWikiPnames:
    fname=WikiPagenameToWindowsFilename(pname)
    Log("   Removing: " + pname + " as "+fname, noNewLine=True)
    deleted=False
    if os.path.isfile(fname + ".xml"):
        os.remove(fname + ".xml")
        Log(" (.xml)", noNewLine=True)
        deleted=True
    if os.path.isfile(fname + ".txt"):
        os.remove(fname + ".txt")
        Log(" (.txt)", noNewLine=True)
        deleted=True
    if deleted:
        countOfDeletedPages+=1
        Log("  ...gone!")
    else:
        countOfUndeletedPages+=1
        Log("   ( files could not be found)")

Log("   "+str(countOfDeletedPages)+" deleted pages removed    "+str(countOfUndeletedPages)+" could not be found")

Log("Done")

