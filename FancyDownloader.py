#
# Program to download an entire wiki (except for history) from Mediawiki and then to keep it synchronized.
# The wiki is downloaded to a directory.  Each wiki page generates two files and possibly a directory:
#     <page>.txt containing the source of the page
#     <page>.xml containing the metadata of the page
#     <page> a directory containing the attached files (created only if there are attached files)

# The basic scheme is to create a list of all pages in the wiki sorted from most-recently-updated to least-recently-updated.
# The downloader then walks the list, downloading new copies of each page which is newer on the wiki than in the local copy.
#    It stops when it finds a page where the local copy is up-to-date
#          (Note that this leave it vulnerable to a case where the downloader fails partway through and updates some pages and not others.
#          The next time it is run, if any pages have been updated in the meantime, the massed pages won't be noticed.
#          Since the alternative is to check every page every time, and since this was written to deal with a wiki with >20K pages, it is an accepted issue to be dea;lt with by hand.)
#    The next step is to compare the list of all local .txt files with the list of all pages, and to download any which are missing.
#          (Note that this does not deal with deleted .xml files or deleted attached files.  This fairly cheap to check, so it might be a useful enhancement.)
#    The final step is to look for local .txt files which are not on the wiki.  These will typically be files which have been deleted on the wiki.  They are deleted locally.

# The synced wiki will be put into a directory 'site' one level up from the Python code.

from __future__ import annotations
import pywikibot
import xml.etree.ElementTree as ET
import os
import sys
import socket
import threading
import queue
import datetime
from datetime import timedelta
from urllib.parse import urlparse
import tkinter as tk
from tkinter import scrolledtext

from pywikibot.exceptions import NoPageError

# Make sure this script's own directory (where the HelpersPackage/Log symlinks live) is on the import path,
# regardless of how we're launched (command line, Task Scheduler, or the PyCharm debugger).
_scriptDir=os.path.dirname(os.path.abspath(__file__))   # captured before any chdir, so the log path below resolves correctly
sys.path.insert(0, _scriptDir)

from Log import Log, LogOpen
from HelpersPackage import WikiPagenameToWindowsFilename, WindowsFilenameToWikiPagename

def main():
    # ############################################################################################
    # ###################################  Main  #################################################
    # ############################################################################################

    # ---------------------------------------------------------------------------------------------
    # Cloudflare bypass (temporary).  Cloudflare currently serves a bot-challenge (403 "Just a moment")
    # on fancyclopedia.org, which blocks pywikibot entirely.  As a workaround we connect straight to the
    # wiki's origin server by its IP -- the same trick ConEditor's FTP uses for fanac.org -- so Cloudflare
    # is out of the path.  Set bypassCloudflare=False once Cloudflare is fixed (e.g. allowlist /api.php) to
    # return to the normal, TLS-verified route through the domain.
    #
    # This must run before pywikibot.Site() below, because the very first API call builds the site family.
    bypassCloudflare=True
    if bypassCloudflare:
        import urllib3, pywikibot.family, pywikibot.comms.http
        originIP="162.246.254.57"       # fancyclopedia.org's origin server (change this if the wiki is rehosted)
        _realGetaddrinfo=socket.getaddrinfo
        socket.getaddrinfo=lambda host, *a, **k: _realGetaddrinfo(originIP if host == "fancyclopedia.org" else host, *a, **k)
        # The origin presents the host's own TLS cert, not one valid for fancyclopedia.org (Cloudflare normally
        # supplies the public cert), so skip verification for this connection.  Acceptable because we pin to a known
        # origin IP; be aware that with verification off, the wiki login is only as safe as the path to the origin.
        # verify_SSL_certificate covers the API calls; FilePage.download() (the binary photos) goes through the shared
        # requests session directly, bypassing that, so turn verification off on the session too.
        pywikibot.family.Family.verify_SSL_certificate=lambda self, code: False
        pywikibot.comms.http.session.verify=False
        urllib3.disable_warnings()      # silence the "unverified HTTPS request" warnings
        print("*** Cloudflare bypass active: connecting directly to the wiki origin at "+originIP)

    # This opens the site specified by user-config.py with the credential in user-password.py.
    fancy=pywikibot.Site()

    # Change the working directory to the destination of the downloaded wiki.
    # A failure here is reported to the log window (we run in a worker thread, so no Tk dialog from here).
    cwd=os.getcwd()
    path=os.path.join(cwd, "..\\site")
    try:
        os.chdir(path)
        os.chmod(path, 0o777)
        # File: pages (photos and other uploads) are stored under this subdirectory of the site
        os.makedirs("Files", exist_ok=True)
    except OSError as e:
        print(f"*** Could not set up the download directory: {path}")
        print(f"      {type(e).__name__}: {e}")
        print("      Make sure the 'site' folder exists one level up from the code and is writable.")
        return
    del path

    # Write the logs next to the executable (not into the 'site' folder we just chdir'd into), using the standard names.
    exeDir=os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else _scriptDir
    LogOpen(os.path.join(exeDir, "Log - FancyDownloader.log"), os.path.join(exeDir, "Log - FancyDownloader - Error.log"))

    # Forced (re)download modes -- independent of each other:
    #   downloadAllPages -> (re)download every non-File page on the wiki (a full rebuild of the main local copy).
    #   downloadAllFiles -> (re)download every File: page (photos etc.) into Files/.
    # Leave both False for routine incremental syncing, where only changed/missing pages are fetched.
    downloadAllPages=False
    downloadAllFiles=False
    if downloadAllPages:
        Log("*** downloadAllPages is True: every non-File page will be (re)downloaded -- expect a large, slow run.")
    if downloadAllFiles:
        Log("*** downloadAllFiles is True: every File: page (photo) will be (re)downloaded -- expect a large, slow bulk download. Set it to False once the initial download is complete.")

    # Look for a file called "override.txt" -- if it exists, load those pages and do nothing else.
    # Override.txt contains a list of page names, one name per line.
    #
    # NOTE NOTE NOTE: Review this carefully before using, as the rest of the code has evolved!
    #
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
    #     for wikiPagename in override:
    #         if DownloadPage(fancy, wikiPagename, None):
    #             countDownloadedPages+=1
    #     exit()

    # Get list of pages on the wiki
    # The strategy will be to first get a list of *all* updates sorted by date of last modification
    # We'll then get rid of all but the most recent modification of each page.
    # Note that we're using the recentchanges() call because the allpages() call doesn't return date of update.
    # Note also that this list will contain pages that have been *deleted* on the wiki
    # Totals are collected here as they're logged, then reprinted together as a single block at the end.
    summary: list[str]=[]
    def Total(line: str, isError: bool=False):
        Log(line, isError=isError)
        summary.append(line)

    # Verify we can actually reach the wiki before doing anything else.  A Cloudflare bot-challenge (a 403 "Just a
    # moment" page) or the site being down returns non-JSON, which pywikibot surfaces deep in the stack as
    # SiteDefinitionError.  Catch it here and report clearly instead of grinding through every namespace and then
    # crashing with a raw traceback.  (server_time is cached, so we reuse it for the recentchanges query below.)
    try:
        current_time=fancy.server_time()
    except Exception as e:
        Log(f"***Cannot reach the wiki API: {e}", isError=True)
        Log("   This is usually a Cloudflare bot-challenge (a 403 'Just a moment' page) or the site being down --", isError=True)
        Log("   not a problem with the local copy, and nothing was changed. Try again later.", isError=True)
        return

    Log("Download list of all pages from the wiki")
    wikiPagenames: list[str]=[]
    wikiListComplete=True       # Cleared if any namespace fails to download fully; we then skip deletions to avoid removing pages that still exist
    for ns in fancy.namespaces:
        # Note that the namespaces are integers, and negative namespaces may be ignored
        if ns < 0 or ns == 6:       #TODO: NS 6 is File:  We need to be able to download it.
            continue
        Log(f"Trying Namespace {ns}: {fancy.namespaces[ns].canonical_name}")
        try:
            for page in fancy.allpages(namespace=ns):
                # Split on the first colon into namespace and page name
                sv=str(page).strip("[]")  # Drop leading and trailing square brackets
                assert sv.find(":") > 0
                parts=sv.split(":", 1)
                wikiPagenames.append(parts[1])
        except Exception as e:
            wikiListComplete=False
            Log(f"   ***Exception while listing namespace {ns}: {e}", isError=True)
        Log(f"Namespace {ns} complete. Count of pages={len(wikiPagenames)}")
    Total(f"   Number of pages on wiki: {len(wikiPagenames)}")

    Log("Download list of recent pages (those updated in the last 120 days), sorted from most- to least-recently-updated")
    iterator=fancy.recentchanges(start=current_time, end=current_time-timedelta(days=120))  # Not for all time, just for the last 120 days (current_time fetched in the reachability check above)
    recentWikiPages: list[dict]=[]
    for v in iterator:
        recentWikiPages.append(v)

    Total(f"   Downloaded list of changes includes {len(recentWikiPages)} items")
    # allWikiPages=[val for val in allWikiPages if val["title"] == "Third Foundation"]

    # Get rid of the older instances of each page.
    # Use a dictionary which only contains the latest version
    tempDict: dict[str, dict]={}
    for p in recentWikiPages:
        pagename=p["title"]
        if pagename not in tempDict.keys() or p["timestamp"] > tempDict[pagename]["timestamp"]:
            tempDict[pagename]=p

    # Recreate the listOfAllWikiPages from the de-duped dictionary
    recentWikiPages=list(tempDict.values())
    Total("   After de-duping, there are "+str(len(recentWikiPages))+" pages left")

    # Sort the list of all pages by timestamp
    def sorttime(page):
        return page["timestamp"]

    recentWikiPages=sorted(recentWikiPages, key=sorttime, reverse=True)
    Log("   The oldest page change listed is "+str(recentWikiPages[-1]["timestamp"]))

    # This list includes pages which are referred to in the wiki, but which have not been created yet.  We don't want them.
    uncreatedWikiPagenames=[val["title"] for val in recentWikiPages if val["oldlen"] == 0 and val["newlen"] == 0]
    Total(f"   There are {len(uncreatedWikiPagenames)} recent pages which are referenced on the wiki, but have not yet been created there. They will be ignored")

    recentWikiPagenames=[val["title"] for val in recentWikiPages]
    createdWikiPagenames=list(set(recentWikiPagenames)-set(uncreatedWikiPagenames))
    Total(f"   There are {len(createdWikiPagenames)} recent pages that exist on the wiki")

    # Get the list of pages from the local copy of the wiki and use that to create lists of missing pages and deleted pages
    Log("Creating list of local files")
    # Since all local copies of pages must have a .txt file, listOfAllDirPages will contain the file name of each page (less the extension)
    # So we want a list of just those names stripped of the extension
    # We also have to back-convert the filenames to get rid of the ;xxxx; that we used to replace certain special characters.
    localFilenamesTxt=[p[:-4] for p in os.listdir(".") if p.endswith(".txt")]
    localFilenamesXml=[p[:-4] for p in os.listdir(".") if p.endswith(".xml")]

    # Create a list of all file names that have *both* .txt and .xml files
    localFilenames=list(set(localFilenamesTxt)&set(localFilenamesXml))  # Union of set of names of xml files and set of names of txt files yields all pages, partial and complete
    Total("    There are "+str(len(localFilenames))+" pages which are in the local copy")

    # Create a list of all file names that have one or the other but not both.
    partialLocalFilenames: list[str]=list(set(localFilenamesTxt)^set(localFilenamesXml))  # Symmetric difference yields list of partial local copies of pages
    partialLocalFilenames=[p for p in partialLocalFilenames if (not p.startswith("Log 202") and not p.startswith("Error 202"))]  # Ignore log files that find there way here
    if len(partialLocalFilenames) == 0:
        Total("    There are no partial page downloads")
    else:
        Total(f"   There are {len(partialLocalFilenames)} partial page downloads required")
        for pname in partialLocalFilenames:
            DownloadPage(fancy, WindowsFilenameToWikiPagename(pname), None)

    # Figure out what pages are missing from the local copy and download them.
    # We do this because we may have at some point failed to make a local copy of a new page.  If it's never updated, it'll never be picked up by the recent changes code.
    localPagenamesSet: set[str]=set([WindowsFilenameToWikiPagename(val) for val in localFilenames])
    wikiPagenamesSet: set[str]=set(wikiPagenames)
    missingLocalPagenames: list[str]=list(wikiPagenamesSet-localPagenamesSet)
    Total(f"   There are {len(missingLocalPagenames)} pages which are on the wiki but not in the local copy.")

    # TODO: Really ought to take into account changes with "logtype" == delete, as those are deletions, not updates
    deletedWikiPagenames=list(localPagenamesSet-wikiPagenamesSet)
    Total(f"   There are {len(deletedWikiPagenames)} pages which are in the local copy, but not on the wiki.")

    # Download pages which exist in the website but not in the disk copy
    Log("Downloading missing pages...")
    countMissingPages=0
    countStillMissingPages=0
    if len(missingLocalPagenames) == 0:
        Total("   There are no missing pages")
    else:
        for pname in missingLocalPagenames:
            if DownloadPage(fancy, pname, None):
                countMissingPages+=1
            else:
                countStillMissingPages+=1
        Total(f"   {countMissingPages} missing pages downloaded     {countStillMissingPages} could not be downloaded")

    # Download the recently updated pages until we start finding pages we already have the most recent version of
    #
    # stoppingCriterion controls how long the update runs
    # stoppingCriterion:
    #   >0 --> Run until we have encountered stoppingCriterion consecutive pages that don't need updates
    #   =0 --> Run through all pages (this is slow and resource-intensive)
    # This is used to handle cases where the downloading and comparison process has been interrupted before updating all changed pages.
    # In that case there will be a wodge of up-to-date recently-changed pages before the pages that were past the interruption.
    # StoppingCriterion needs to be big enough to get past that wodge.
    stoppingCriterion=2500
    Log("Downloading recently updated pages...")
    countUpToDatePages=0
    countDownloadedPages=0
    for page in recentWikiPages:
        pageName=page["title"]
        if pageName in createdWikiPagenames:
            if DownloadPage(fancy, pageName, page):
                countDownloadedPages+=1
            else:
                countUpToDatePages+=1
                if 0 < stoppingCriterion < countUpToDatePages:
                    Log("      Ending downloads. "+str(stoppingCriterion)+" up-to-date pages found")
                    break
    Total(f"   {countDownloadedPages} updated pages downloaded")

    # Optionally force the (re)download of non-File pages.
    #   downloadAllPages -> force every non-File page; or hand-populate forcedWikiDownloadsPagenames for a subset, e.g. [x for x in wikiPagenames if x.lower()[0] == 'v']
    forcedWikiDownloadsPagenames: list[str]=list(wikiPagenames) if downloadAllPages else []
    if len(forcedWikiDownloadsPagenames) > 0:
        Log("Begin forced downloading of pages...")
        countForcedPages=0
        countForcedFailures=0
        for pagename in forcedWikiDownloadsPagenames:
            if DownloadPage(fancy, pagename, None):
                countForcedPages+=1
            else:
                countForcedFailures+=1
        Total(f"   {countForcedPages} forced pages downloaded     {countForcedFailures} could not be downloaded")

    # ------------------------------------------------------------------------------------------------
    # Sync the File: namespace (NS 6) -- photos and other uploads.
    # File pages are stored under the Files/ subdirectory (source .txt, metadata .xml, and the binary itself),
    # kept separate from the flat main-namespace files so the missing/deletion logic above never touches them.
    # Note: a File page whose name ends in .txt or .xml could collide with the .txt/.xml listing below; this is
    # ignored because Fancyclopedia File pages are essentially all photos (.jpg/.png/.gif).
    # downloadAllFiles (set near the top of main) selects full re-download vs. missing-only.
    Log("Listing File: pages on the wiki...")
    wikiFilePagenames: list[str]=[]
    fileListComplete=True
    try:
        for page in fancy.allpages(namespace=6):
            wikiFilePagenames.append(page.title())
    except Exception as e:
        fileListComplete=False
        Log(f"   ***Exception while listing the File namespace: {e}", isError=True)
    Total(f"   There are {len(wikiFilePagenames)} File: pages on the wiki")

    # Diagnostic (future-proofing): MediaWiki names are case-sensitive but Windows is not, so flag the cases that rely on that difference.
    #   - non-lowercase extensions are where the binary's real suffix differs from our case-encoded stem (handled below, but worth knowing how common)
    #   - titles that become identical once lowercased would collide on Windows if not for the ^^ encoding
    nonLowercaseExt=[t for t in wikiFilePagenames if os.path.splitext(t)[1] != os.path.splitext(t)[1].lower()]
    if nonLowercaseExt:
        Total(f"   {len(nonLowercaseExt)} File: pages have a non-lowercase extension")
        for t in nonLowercaseExt:
            Log("      non-lowercase extension: "+t)
    loweredFileTitles: dict[str, list[str]]={}
    for t in wikiFilePagenames:
        loweredFileTitles.setdefault(t.lower(), []).append(t)
    caseCollisions=[v for v in loweredFileTitles.values() if len(v) > 1]
    if caseCollisions:
        Total(f"   ***{len(caseCollisions)} sets of File: pages differ only by letter case and would collide on Windows", isError=True)
        for v in caseCollisions:
            Log("      case collision: "+str(v), isError=True)

    # Build the set of File pages already in the local Files/ directory (those with both a .txt and an .xml)
    localFileTxt=[p[:-4] for p in os.listdir("Files") if p.endswith(".txt")]
    localFileXml=[p[:-4] for p in os.listdir("Files") if p.endswith(".xml")]
    localFileStems=set(localFileTxt)&set(localFileXml)
    localFilePagenames: set[str]={"File:"+WindowsFilenameToWikiPagename(s) for s in localFileStems}

    # File pages whose .txt/.xml are present but whose binary (stored at the stem itself) is missing -- e.g. an earlier
    # download that failed after the metadata was written.  Their up-to-date .xml would otherwise make them look
    # complete and be skipped, so re-fetch them even in incremental mode.  Restrict to pages still on the wiki.
    missingBinaryPagenames={"File:"+WindowsFilenameToWikiPagename(s) for s in localFileStems
                            if not os.path.isfile(os.path.join("Files", s))} & set(wikiFilePagenames)
    if missingBinaryPagenames:
        Total(f"   {len(missingBinaryPagenames)} File: pages have their .txt/.xml but a missing binary -- re-fetching")

    if downloadAllFiles:
        fileTargets=wikiFilePagenames
    else:
        # File pages we don't have at all, plus ones missing only their binary
        fileTargets=list((set(wikiFilePagenames)-localFilePagenames) | missingBinaryPagenames)
    if len(fileTargets) == 0:
        Total("   There are no File: pages to download")
    else:
        Log(f"Downloading {len(fileTargets)} File: pages...")
        countFiles=0
        countFileFailures=0
        for fp in fileTargets:
            if DownloadPage(fancy, fp, None):
                countFiles+=1
            else:
                countFileFailures+=1
        Total(f"   {countFiles} File: pages downloaded     {countFileFailures} could not be downloaded")

    # Delete local File pages which are no longer on the wiki (removes the .xml, .txt, and the binary)
    if not fileListComplete:
        Total("   The File: page list was incomplete (the namespace failed to download), so File deletions are being skipped", isError=True)
    else:
        deletedFilePagenames=list(localFilePagenames-set(wikiFilePagenames))
        if len(deletedFilePagenames) == 0:
            Total("   There are no deleted File: pages to remove")
        else:
            Log("Removing deleted File: pages...")
            countDeletedFiles=0
            for pname in deletedFilePagenames:
                stem=LocalStemForPage(pname)
                removedAny=False
                for suffix in (".xml", ".txt", ""):     # metadata, source, and the binary itself (no extension)
                    if os.path.isfile(stem+suffix):
                        os.remove(stem+suffix)
                        removedAny=True
                if removedAny:
                    countDeletedFiles+=1
                    Log("   Removed: "+pname)
            Total(f"   {countDeletedFiles} deleted File: pages removed")

    # Delete local copies of pages which have disappeared from the wiki
    # Note that we don't detect and delete local copies of attached files which have been removed from the wiki when the associated wiki page remains.


    if not wikiListComplete:
        Total("   The wiki page list was incomplete (a namespace failed to download), so deletions are being skipped to avoid removing pages that still exist", isError=True)
    elif len(deletedWikiPagenames) == 0:
        Total("   There are no deleted pages to remove")
    else:
        Log("Removing deleted pages...")
        countOfDeletedPages=0
        countOfUndeletedPages=0
        for pname in deletedWikiPagenames:
            fname=WikiPagenameToWindowsFilename(pname)
            Log("   Removing: "+pname+" as "+fname, noNewLine=True)
            deleted=False
            if os.path.isfile(fname+".xml"):
                os.remove(fname+".xml")
                Log(" (.xml)", noNewLine=True)
                deleted=True
            if os.path.isfile(fname+".txt"):
                os.remove(fname+".txt")
                Log(" (.txt)", noNewLine=True)
                deleted=True
            if deleted:
                countOfDeletedPages+=1
                Log("  ...gone!")
            else:
                countOfUndeletedPages+=1
                Log("   ( files could not be found)")

        Total(f"   {countOfDeletedPages} deleted pages removed    {countOfUndeletedPages} could not be found")

    Log("Done")

    print("\n\n----------------------")
    print("Summary of totals:")
    print("\n".join(summary))

#-----------------------------------------
# Find text bracketed by <b>...</b>
# Input is of the form <b stuff>stuff</b>stuff
# Return the contents of the first pair of brackets found, the remainder of the input string up to </b>, and anything leftover afterwards (the three stuffs)
def FindBracketedText(s: str, b: str) -> tuple[str, str,str]|None:
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
def GetHrefAndTextFromString(s: str) -> tuple[str|None, str|None]:
    s=FindBracketedText(s, "a")
    if s[0] == "":
        return None, None

    # Remove the 'href="' from trailing '"' from the string
    return s[0][6:-1], s[1]


def DecodeDatetime(dtstring: str) -> datetime.datetime:
    if dtstring is None:
        return datetime.datetime(1950, 1, 1, 1, 1, 1)    # If there's no datetime, return something early
    if not dtstring.endswith("+00:00"):
        raise ValueError("Could not decode datetime: '"+dtstring+"'")
    return datetime.datetime.strptime(dtstring[:-6], '%Y-%m-%dT%H:%M:%S')


# Return the local path stem (no extension) where a page's files are stored.
# File: pages go under the Files/ subdirectory with the namespace prefix stripped (the folder implies it); everything else is stored flat.
def LocalStemForPage(wikiPagename: str) -> str:
    if wikiPagename.startswith("File:"):
        return os.path.join("Files", WikiPagenameToWindowsFilename(wikiPagename.split(":", 1)[1]))
    return WikiPagenameToWindowsFilename(wikiPagename)


# Download a page from Mediawiki and possibly store it locally.
# The page's contents are stored in their files, the source in <saveName>.txt, the rendered HTML in <saveName>..html, and all the page meta information in <saveName>.xml
# Setting pageData to None forces downloading of the page, reghardless of whether it is already stored locally.  This is mostly useful to overwrite the hidden consequences of old sync errors
# The return value is True when the local version of the page has been updated, and False otherwise
def DownloadPage(fancy, wikiPagename: str, pageData: dict|None) -> bool:
    localFilename=LocalStemForPage(wikiPagename)   # The windows-filesystem-compatible local path stem (under Files/ for File: pages, flat otherwise)

    # If we set updateAll to True, then we skip the date che    cks and always do the update
    action="Downloading"
    if pageData is not None:
        action="Updating"
        # NOTE: This relies on the update times stored in the local file's xml and in the last update time data from pageData
        # It will not detect incompletely downloaded pages if the xml file exists
        # Check the timestamps and only update if the page on the server is newer than the local copy

        # Get the updated time for the local version
        if os.path.isfile(localFilename+".xml"):
            # If no xml file exists, we want to do the download, since the local copy is missing or incomplete
            tree=ET.parse(localFilename+".xml")
            doc=tree.getroot()
            localTimestamp=doc.find("timestamp").text

            # Get the wiki page's updated time
            wikiTimestamp=pageData["timestamp"]

            # We return True whenever we have just downloaded a page which was already up-to-date locally
            if wikiTimestamp <= localTimestamp:
                return False

    # OK, we're going to download this one
    if wikiPagename == localFilename:
        Log("   "+action+": '"+wikiPagename+"'")
    else:
        Log("   "+action+": '"+wikiPagename+"' as '"+localFilename+"'")

    page=pywikibot.Page(fancy, wikiPagename)
    if page.text is None or len(page.text) == 0:
        Log("       empty page: "+wikiPagename)

    # Write the page to temporary files first, then move them into place only once both have been
    # written successfully.  If we're interrupted mid-write, the previous complete .txt/.xml pair is
    # left intact rather than a half-updated page.  (The next run still repairs any partial pair via
    # the symmetric-difference check; this just keeps the common case clean.)
    text=page.text
    txtTemp=localFilename+".txt.tmp"
    if text is not None:
        with open(txtTemp, "wb") as file:
            file.write(text.encode("utf8"))

    # Write the page's metadata to a temporary .xml file
    xmlTemp=localFilename+".xml.tmp"
    xmlWritten=False
    try:
        SaveMetadata(xmlTemp, page)
        xmlWritten=True
    except NoPageError as s:
        if "Fancyclopedia 3:" not in str(s):
            Log(f"SaveMetaData('{localFilename}.xml') failed with a NoPageError exception: '{s}'")
            if os.path.exists(txtTemp):
                os.remove(txtTemp)
            return False
        Log(f"Ignored: NoPageError '{s}'")

    # Both files are written: move them into place back-to-back to minimize any inconsistency window.
    if text is not None:
        os.replace(txtTemp, localFilename+".txt")
    elif os.path.exists(localFilename+".txt"):
        # If there's no text, delete any existing txt file
        os.remove(localFilename+".txt")
    if xmlWritten:
        os.replace(xmlTemp, localFilename+".xml")

    # Is this a file (e.g. a photo)?  If so, download the binary itself to the same Files/ stem, alongside its .txt/.xml.
    if page.is_filepage():
        # pywikibot's download() forces the saved file's suffix to the URL's real suffix, which would diverge from our
        # case-encoded stem (e.g. '.J^^P^^G^^' -> '.JPG').  So download to a throwaway temp name (no extension, so the
        # forced suffix just gets appended) and move the result onto the exact stem, keeping the binary consistent with
        # its .txt/.xml.  Wrapped so one bad download (IOError, network, hash mismatch) doesn't abort the whole bulk run.
        try:
            filePage=pywikibot.FilePage(fancy, wikiPagename)
            suffix=os.path.splitext(urlparse(filePage.get_file_url()).path)[1]
            tempName=os.path.join("Files", "_download")
            if filePage.download(tempName):
                os.replace(tempName+suffix, localFilename)
                Log("       binary downloaded to "+localFilename)
            else:
                Log(f"       ***binary download failed (bad status or hash mismatch) for {wikiPagename}", isError=True)
        except Exception as e:
            Log(f"       ***binary download raised for {wikiPagename}: {e}", isError=True)


    return True


# Save the wiki page's metadata to an xml file
def SaveMetadata(localName: str, pageData: pywikibot.Page) -> None:
    root = ET.Element("data")

    ET.SubElement(root, "title").text=str(pageData.title())
    ET.SubElement(root, "filename").text=str(pageData.title(as_filename=True))
    ET.SubElement(root, "urlname").text=str(pageData.title(as_url=True))
    ET.SubElement(root, "isRedirectPage").text=str(pageData.isRedirectPage())
    # numrevisions stays on the private _revisions cache: the only public alternative (page.revisions())
    # walks revision history (O(N) network), and this value is just the count of revisions loaded so far anyway.
    ET.SubElement(root, "numrevisions").text=str(len(pageData._revisions))
    ET.SubElement(root, "pageid").text=str(pageData.pageid)
    # revid/exists are cached by the earlier page.text load, so the public accessors add no network traffic.
    if not pageData.exists():
        ET.SubElement(root, "revid").text="0"
    else:
        ET.SubElement(root, "revid").text=str(pageData.latest_revision_id)
    ET.SubElement(root, "edittime").text=str(pageData.latest_revision.timestamp)
    ET.SubElement(root, "permalink").text=str(pageData.permalink())

    ET.SubElement(root, "categories").text=str([c for c in pageData.categories()])
    #ET.SubElement(root, "backlinks").text=str([c for c in pageData.backlinks()])
    #ET.SubElement(root, "linkedPages").text=str([c for c in pageData.linkedPages()])

    ET.SubElement(root, "timestamp").text=str(pageData.latest_revision.timestamp)
    ET.SubElement(root, "user").text=str(pageData.latest_revision.user)

    # And write the xml out to file <localName>.xml.
    tree = ET.ElementTree(root)
    tree.write(localName)



# ------------------------------------------------------------------------------------------------
# Live log window.  RunWithLogWindow() runs the work function in a background (daemon) thread while a
# scrollable, minimizable Tk window shows everything it prints.  The Cancel button aborts the run and
# closes the app; when the work finishes the window is raised to the front and the button becomes Close.
class _StdoutTee:
    # Writes to the original stream (the console) AND queues the text for the log window.
    def __init__(self, original, q: queue.Queue):
        self.original=original
        self.queue=q
    def write(self, text: str):
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        self.queue.put(text)
    def flush(self):
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass


def RunWithLogWindow(work) -> None:
    q: queue.Queue=queue.Queue()
    sys.stdout=_StdoutTee(sys.stdout, q)
    sys.stderr=_StdoutTee(sys.stderr, q)

    root=tk.Tk()
    root.title("FancyDownloader")
    root.geometry("900x600")

    done=threading.Event()

    def close():
        if done.is_set():
            root.destroy()      # work already finished -- exit cleanly
        else:
            os._exit(1)         # still running -- hard-abort the whole app (the worker is a daemon thread)
    button=tk.Button(root, text="Cancel", command=close, width=12)
    button.pack(side="bottom", pady=4)
    root.protocol("WM_DELETE_WINDOW", close)

    box=scrolledtext.ScrolledText(root, wrap="word", font=("Consolas", 9))
    box.pack(side="top", fill="both", expand=True)
    box.configure(state="disabled")

    def poll():
        # Drain queued output into the widget (on the Tk main thread); auto-scroll only if already at the bottom.
        chunks=[]
        try:
            while True:
                chunks.append(q.get_nowait())
        except queue.Empty:
            pass
        if chunks:
            atBottom=box.yview()[1] >= 0.999
            box.configure(state="normal")
            box.insert("end", "".join(chunks))
            box.configure(state="disabled")
            if atBottom:
                box.see("end")
        if done.is_set() and q.empty():
            # Finished: bring the window to the front and switch Cancel -> Close.
            button.config(text="Close")
            root.title("FancyDownloader -- finished")
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.after(700, lambda: root.attributes("-topmost", False))
            return          # stop polling
        root.after(100, poll)

    def worker():
        try:
            work()
        except Exception:
            import traceback
            traceback.print_exc()   # captured by the tee -> shown in the window
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    RunWithLogWindow(main)
