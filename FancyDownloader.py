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
from datetime import timedelta
import xml.etree.ElementTree as ET
import os
import datetime


#-----------------------------------------
# Convert page names to legal Windows filename
def PageNameToFilename(pname: str):
    return pname.replace(";", ";semi;").replace("*", ";star;").replace("/", ";slash;").replace("?", ";ques;").replace('"', ";quot;").replace("<", ";lt;").replace(">", ";gt;").replace("\\", ";back;").replace("|", ";bar;").replace(":", ";colon;")


#-----------------------------------------
# Find text bracketed by <b>...</b>
# Input is of the form <b stuff>stuff</b>stuff
# Return the contents of the first pair of brackets found, the remainder of the input string up to </b>, and anything leftover afterwards (the three stuffs)
def FindBracketedText(s: str, b: str):
    strlower=s.lower()
    # Find <b ...>
    l1=strlower.find("<"+b.lower()) # Look for <b
    if l1 == -1:
        return "", "", s
    l2=strlower.find(">", l1)       # Look for following >
    if l2 == -1:
        print("***Error: no terminating '>' found in "+strlower+"'")
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
def GetHrefAndTextFromString(s: str):
    s=FindBracketedText(s, "a")
    if s[0] == "":
        return None, None

    # Remove the 'href="' from trailing '"' from the string
    return s[0][6:-1], s[1]

def DecodeDatetime(dtstring: str):
    if dtstring is None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '")+dtstring+"'"
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')

# Download a page from Wikidot and possibly store it locally.
# The page's contents are stored in their files, the source in <saveName>.txt, the rendered HTML in <saveName>..html, and all of the page meta information in <saveName>.xml
# Setting updateAll to True allows a forced downloading of the page, reghardless of whether it is already stored locally.  This is mostly useful to overwrite the hidden consequences of old sync errors
# The return value is True when the local version of the page has been updated, and False otherwise
def DownloadPage(fancy, pageName: str, pageData: dict, updateAll: bool):
    #time.sleep(0.05)    # Wikidot has a limit on the number of RPC calls/second.  This is to throttle the download to stay on the safe side.

    page=pywikibot.Page(fancy, pageName)
    if page.text is None or len(page.text) == 0:
        return

    pageName=PageNameToFilename(pageName)

    # NOTE: This relies on the update times stored in the local file's xml and in the wiki page's updated_at metadata
    # It will not detect incompletely downloaded pages if the xml file exists
    # If we haven't selected updateAll, then check the timestamps and only update if the page on the server is newer than the local copy
    if not updateAll:
        # Get the updated time for the local version
        if os.path.isfile(pageName+".xml"):
            # If no xml file exists, we want to do the download, since the local copy is missing or incomplete
            tree=ET.parse(pageName+".xml")
            doc=tree.getroot()
            localTimestamp=doc.find("timestamp").text

            # Get the wiki page's updated time
            wikiTimestamp=pageData["timestamp"]

            # We return True whenever we have just downloaded a page which was already up-to-date locally
            if wikiTimestamp <= localTimestamp:
                return False

    # OK, we're going to download this one
    print("   Updating: '"+pageName+"'")

    # Write the page source to <pageName>.txt
    text=page.text
    fname=PageNameToFilename(pageName)+".txt"
    if text is not None:
        with open(fname, "wb") as file:
            file.write(text.encode("utf8"))
    else:
        # If there's no text, delete any existing txt file
        if os.path.exists(fname):
            os.remove(fname)

    # Write the page's metadata to <pageName>.xml
    SaveMetadata(fname, page)

    # # Check for attached files
    # # If any exist, save them in a directory named <pageName>
    # # If none exist, don't create the directory
    # # Note that this code does not delete the directory when previously-existing files have been deleted from the wiki page
    # fileNameList=client.ServerProxy(url).files.select({"site": "fancyclopedia", "page": wikiName})
    # downloadFailures=[]
    # if len(fileNameList) > 0:
    #     if not os.path.exists(pageName):
    #         os.mkdir(pageName)   # Create a directory for the files and metadata
    #         os.chmod(pageName, 0o777)
    #     for fileName in fileNameList:
    #         try:
    #             fileStuff = client.ServerProxy(url).files.get_one({"site": "fancyclopedia", "page": wikiName, "file": fileName})    # Download the file's content and metadata
    #         except client.Fault:
    #             print("**** client.Fault loading "+fileName+". The file is probably too big.")
    #             downloadFailures.append(fileName)
    #             continue
    #         path=os.path.join(os.getcwd(), pageName, fileName)
    #         content=base64.b64decode(fileStuff["content"])
    #         with open(path, "wb+") as file:
    #             file.write(content)     # Save the content as a file
    #
    #         # Now save the file's metadata in an xml file named for the file
    #         del fileStuff["content"]    # We don't want to store the file's content in the metadata since we already saved it as a file.
    #         SaveMetadata(os.path.join(pageName, fileName), fileStuff)

    # # Wikidot has a limit on the size of a file which can be downloaded through the API which is much smaller than the filesize limit on the site.
    # # If any files failed to download, try to download then using Selenium
    # # This should get the file, but can't get the metadata.
    # if len(downloadFailures) > 0:
    #     # Instantiate the web browser Selenium will use. For now, we're opening it anew each time.
    #     browser=webdriver.Firefox()
    #     # Open the Fancy 3 page in the browser
    #     browser.get("http://fancyclopedia.org/"+pageName+"/noredirect/t")
    #     elem=browser.find_element_by_id('files-button')
    #     elem.send_keys(Keys.RETURN)
    #     time.sleep(0.7)  # Just-in-case
    #     # wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'page-files')))
    #
    #     try:
    #         els=browser.find_element_by_class_name("page-files").find_elements_by_tag_name("tr")
    #     except:
    #         print('******find_element_by_class_name("page-files").find_elements_by_tag_name("tr") failed')
    #
    #     for i in range(1, len(els)):
    #         h=els[i].get_attribute("outerHTML")
    #         url, linktext=GetHrefAndTextFromString(h)
    #         if linktext in downloadFailures:
    #             urllib.request.urlretrieve("http://fancyclopedia.org"+url, os.path.join(pageName, linktext))
    #             print("     downloading big file "+linktext)
    #     browser.close()

    return True

# Save the wiki page's metadata to an xml file
def SaveMetadata(localName: str, pageData: dict):
    root = ET.Element("data")
    wikiUpdatedTime = None

    ET.SubElement(root, "timestamp").text=str(pageData.latest_revision.timestamp)
    ET.SubElement(root, "numrevisions").text=str(len(pageData._revisions))
    ET.SubElement(root, "pageid").text=str(pageData.pageid)
    ET.SubElement(root, "revid").text=str(pageData._revid)
    ET.SubElement(root, "user").text=str(pageData.latest_revision.user)

    # And write the xml out to file <localName>.xml.
    tree = ET.ElementTree(root)
    tree.write(localName + ".xml")
    return wikiUpdatedTime

# Get the wiki page's update time from the its metadata
def GetPageWikiTime(localName, pageData):
    for itemName in pageData:
        if itemName == "updated_at":  # Save the updated time
            return pageData[itemName]


# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# Main

# This opens the site specified by user-config.py with the credential in user-password.py
fancy=pywikibot.Site()

# Change the working directory to the destination of the downloaded wiki
cwd=os.getcwd()
path=os.path.join(cwd, "..\\site")
os.chdir(path)
os.chmod(path, 0o777)
del cwd, path

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
#     print("Downloading override pages...")
#     countDownloadedPages=0
#     for pageName in override:
#         if DownloadPage(fancy, pageName, True):
#             countDownloadedPages+=1
#     exit()

# Now, get list of pages sorted by date of last modification
# The strategy will be to first get a list of *all* updates sorted by date of last modification
# We'll then get rid of all but the most recent modification of each page.
# Note that we're using the recentchanges() call because the allpages() call doesn't return date of update.
print("Get list of all pages from Wikidot, sorted from most- to least-recently-updated")
current_time = fancy.server_time()
iterator=fancy.recentchanges(start = current_time, end=current_time - timedelta(hours=600000))   # Not for all time, just for the last 60 years...
listOfAllWikiPages=[]
for v in iterator:
    listOfAllWikiPages.append(v)
# Now get rid of the older instances of each page.
# Use a dictionary which only contains the latest version
temp={}
for p in listOfAllWikiPages:
    if p["title"] in temp.keys():
        if p["timestamp"] > temp[p["title"]]["timestamp"]:
            temp[p["title"]]=p
    else:
        temp[p["title"]]=p

# No recreate the listOfAllWikiPages from the de-duped dictionary and then sort it
listOfAllWikiPages=list(temp.values())
def sorttime(page):
    return page["timestamp"]
listOfAllWikiPages=sorted(listOfAllWikiPages, key=sorttime, reverse=False)
# TODO: Do we need to fix con here?  (Probably not.)

# Download the recently updated pages until we start finding pages we already have the most recent version of
#
# stoppingCriterion controls how long the update runs
# stoppingCriterion:
#   >0 --> Run until we have encountered stoppingCriterion consecutive pages that don't need updates
#   =0 --> Run through all pages (this is slow and resource-intensive)
# This is used to handle cases where the downloading and comparison process has been interrupted before updating all changed pages.
# In that case there will be a wodge of up-to-date recently-changed pages before the pages that were past the interruption.
# StoppingCriterion needs to be big enough to get past that wodge.
stoppingCriterion=100
print("Downloading recently updated pages...")
countUpToDatePages=0
countDownloadedPages=0
for page in listOfAllWikiPages:
    pageName=page["title"]
    if DownloadPage(fancy, pageName, page, False):
        countDownloadedPages+=1
    else:
        countUpToDatePages+=1
        if stoppingCriterion > 0 and countUpToDatePages > stoppingCriterion:
            print("      "+str(countDownloadedPages)+" pages downloaded")
            print("      Ending downloads. " + str(stoppingCriterion) + " up-to-date pages found")
            break

# Get the page list from the local directory and use that to create lists of missing pages and deleted pages
print("Creating list of local files")
# Since all local copies of pages have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)
# So we want a list of just those names stripped of the extension
listOfAllDirPages=[p[:-4] for p in os.listdir(".") if p.endswith(".txt")]

# Now figure out what pages are missing and download them.
print("Downloading missing pages...")
listOfAllMissingPages = [val for val in listOfAllWikiPages if val not in listOfAllDirPages]  # Create a list of pages which are in the wiki and not downloaded
if len(listOfAllMissingPages) == 0:
    print("   There are no missing pages")
for pageName in listOfAllMissingPages:
    DownloadPage(fancy, pageName, False)

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

