"""
Django views for QuickBBS Gallery
"""
# from django.shortcuts import render
import time
import os
import os.path
import urllib
# from threading import Thread
from django.http import HttpResponse, HttpResponseNotFound
# HttpResponseRedirect
from django.template import loader
from django.views.static import serve
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import authenticate, login
import fastnumbers
import directory_caching
import directory_caching.archives3 as archives
from frontend.config import configdata as configdata
import frontend.thumbnail as thumbnail
import frontend.tools as tools

#
#   Need to be able to set root path for albums directory
#   Need to be able to set root path for thumbnail directory
#
#
# Sending File or zipfile - https://djangosnippets.org/snippets/365/
# thumbnails - https://djangosnippets.org/snippets/20/

CDL = directory_caching.Cache()
CDL.smart_read(os.path.join(configdata["locations"]["albums_path"],
                            "albums").lower())
SIZES = ["sm_thumb", "med_thumb", "lg_thumb"]
THUMBNAIL = thumbnail.Thumbnails()


def is_folder(fqfn):
    """
    Is it a folder?
    """
    return os.path.isdir(fqfn)


def is_file(fqfn):
    """
    Is it a file?
    """
    return os.path.isfile(fqfn)


def is_archive(fqfn):
    # None = not an archive.
    """
    Is it an archive?
    """
    return not directory_caching.archives3.id_cfile_by_sig(fqfn) is None


def return_directory_tnail_filename(directory_to_use):
    """
    Identify candidate in directory for creating a tnail,
    and then return that filename.
    """
    #
    #   rewrite to use return_directory_contents
    #
    data = CDL.return_sort_name(directory_to_use.lower().strip())[0]
    for thumbname in data:
        if thumbname[1].file_extension in thumbnail.THUMBNAIL_DB:
            return os.sep.join([directory_to_use, thumbname[0]])
    return None


def make_thumbnail_fqfns(list_fqfn, size, start=0, end=None):
    """
    list_fqfn is the directory_cache listing of the files that
    need a thumbnail_filename

    return the list of thumbnail_filenames
    """
    if end is None:
        end = len(list_fqfn)
#    thumbnail_obj = thumbnail.Thumbnails()
    thumbnail_list = []
    for fqfn in list_fqfn[start:end]:
        thumbnail_list.append(THUMBNAIL.make_tnail_fsname(
            fqfn[1].fq_filename)[size])
    return thumbnail_list


def verify_login_status(request, force_login=False):
    """
    Verify login status
    """
    username = request.POST['username']
    password = request.POST['password']
    user = authenticate(username=username, password=password)
    if user is not None:
        if user.is_active:
            login(request, user)
            # Redirect to a success page.
        else:
            print "disabled account"
            # Return a 'disabled account' error message
    else:
        print "Invalid login"
        # Return an 'invalid login' error message.


def option_exists(request, option_name):
    """
    Does the option exist in the request.GET
    """
    return option_name in request.GET


def get_option_value(request, option_name, def_value):
    """
    Return the option from the request.get?
    """
    return request.GET.get(option_name, def_value)


def sort_order(request, context):
    """
    Return the query'd sort order from the web page
    """
    if "sort" in request.GET:
        #   Set sort_order, since there is a value in the post
        # pylint: disable=E1101
        request.session["sort_order"] = fastnumbers.fast_int(
            request.GET["sort"], 0)
        context["sort_order"] = fastnumbers.fast_int(request.GET["sort"], 0)
# pylint: enable=E1101
    else:
        context["sort_order"] = request.session.get("sort_order", 0)
    return request, context


def detect_mobile(request):
    """
    Is this a mobile browser?
    """
    return request.META["HTTP_USER_AGENT"].find("Mobile") != -1


def return_prev_next(fqfn, webpath, sortorder):
    """
    Return the previous and next directories for a gallery page
    """
    def get_directory_offset(offset,
                             scan_directory,
                             s_order,
                             current_directory):
        """
        Return the next / previous directory name, per offset
        """
        temp = CDL.return_current_directory_offset(
            scan_directory=scan_directory.lower(),
            current_directory=current_directory,
            sort_type=s_order,
            offset=offset)[1]

        if temp is not None:
            return (os.path.join(scan_directory, temp), temp)
        else:
            return ("", "")

    nextd = get_directory_offset(+1,
                                 scan_directory=os.sep.join(
                                     fqfn.split(os.sep)[0:-1]),
                                 s_order=sortorder,
                                 current_directory=fqfn.split(os.sep)[-1])
    next_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), nextd[1]]),
                nextd[1])

    prev = get_directory_offset(-1,
                                scan_directory=os.sep.join(
                                    fqfn.split(os.sep)[0:-1]),
                                s_order=sortorder,
                                current_directory=fqfn.split(os.sep)[-1])
    prev_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), prev[1]]),
                prev[1])
    return prev_uri[1], next_uri[1]


def read_from_cdl(dir_path, sort_by):
    """ Read from the cached Directory Listings"""
    CDL.smart_read(dir_path)
    cached_files, cached_dirs = CDL.return_sorted(scan_directory=dir_path,
                                                  sort_by=sort_by)
    return cached_dirs + cached_files


def create_validate_thumb(src_file, t_file, t_size, archive_item=0):
    """
    Create the thumbnail & validate the thumbnail's modification date
    """
    if src_file is None:
        return
    THUMBNAIL.validate_thumbnail_file(t_file, src_file)
    if src_file.file_extension == "dir":
        THUMBNAIL.create_thumbnail_from_file(src_filename=src_file.dir_thumb,
                                             t_filename=t_file,
                                             t_size=t_size)
    elif src_file.file_extension in directory_caching.ARCHIVE_FILE_TYPES:
        mem_file = src_file.archive_file.extract_mem_file(
            src_file.archive_file.listings[archive_item])
        if mem_file is not None:
            THUMBNAIL.create_thumbnail_from_memory(memory_image=mem_file,
                                                   t_filename=t_file,
                                                   t_size=t_size)

    else:
        THUMBNAIL.create_thumbnail_from_file(src_filename=src_file.fq_filename,
                                             t_filename=t_file,
                                             t_size=t_size)


def return_archive_icon_fn(cdl_entry):
    pass


def viewgallery(request):
    """
    View the requested Gallery page
    """
    start_time = time.time()
    context = {}
    paths = {}
    context["mobile"] = detect_mobile(request)
    paths["webpath"] = request.path.lower()
    request, context = sort_order(request, context)

    paths["album_viewing"] = configdata["locations"]["albums_path"] +  \
        paths["webpath"].replace("/", os.sep)
    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    if not paths["thumbpath"].endswith("/"):
        paths["thumbpath"] += "/"
#    tnails = THUMBNAIL.Thumbnails()
    cr_thumbs = []
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')
    elif is_archive(paths["album_viewing"]):
        return viewarchive(request, paths["album_viewing"])
    elif is_file(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif is_folder(paths["album_viewing"]):
        global_listing = read_from_cdl(paths["album_viewing"],
                                       context["sort_order"])
        thumbnail_listings = make_thumbnail_fqfns(global_listing, size="small")
        listings = []
        tools.assure_path_exists(paths["fs_thumbpath"])
        for count, dcache in enumerate(global_listing):
            #               0,          1,          ,2                  , 3
            # Listings = fname, dcache entry, web thmbnailpath, thmbnailfs path
            if dcache[1].file_extension in thumbnail.THUMBNAIL_DB:
                cr_thumbs.append((dcache[1],
                                  thumbnail_listings[count],
                                  configdata["configuration"]["sm_thumb"]))
                listings.append((dcache[0], dcache[1],
                                 paths["thumbpath"] +
                                 os.path.split(thumbnail_listings[count])[1],
                                 thumbnail_listings[count],
                                 thumbnail.THUMBNAIL_DB[
                                     dcache[1].file_extension]\
                                 ["BACKGROUND"]))

            elif dcache[1].file_extension == "dir":
                CDL.smart_read(dcache[1].fq_filename.lower())
                dcache[1].dir_thumb = return_directory_tnail_filename(
                    dcache[1].fq_filename.lower())
                if dcache[1].dir_thumb is not None:
                    tfile = os.path.join(
                        os.path.split(dcache[1].fq_filename.lower())[0],
                        os.path.split(dcache[1].fq_filename.lower())[1])
                    cr_thumbs.append((dcache[1],
                                      THUMBNAIL.make_tnail_fsname(tfile)["small"],
                                      configdata["configuration"]["sm_thumb"]))
                    listings.append(
                        (dcache[0], dcache[1],
                         paths["thumbpath"] +\
                             os.path.split(thumbnail_listings[count])[1],
                         thumbnail_listings[count],
                         "#DAEFF5"))
                else:
                    cr_thumbs.append((None,
                                      None,
                                      None))

                    listings.append(
                        (dcache[0], dcache[1],
                         r"/resources/images/folder-close-icon.png",
                         thumbnail_listings[count],
                         "#DAEFF5"))
        context["current_page"] = request.GET.get("page")
        chk_list = Paginator(listings, 30)
        template = loader.get_template('frontend/gallery_listing.html')
        context["page_cnt"] = range(1, chk_list.num_pages+1)
        context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
        context["gallery_name"] = os.path.split(request.path_info)[-1]
        try:
            context["pagelist"] = chk_list.page(context["current_page"])
        except PageNotAnInteger:
            context["pagelist"] = chk_list.page(1)
            context["current_page"] = 1
        except EmptyPage:
            context["pagelist"] = chk_list.page(chk_list.num_pages)
        context["all_listings"] = global_listing

        for entry in cr_thumbs[context["pagelist"].start_index()-1:
                               context["pagelist"].end_index()]:
            #
            # Send the dcache entry to create, to give archive data.
            #
            create_validate_thumb(src_file=entry[0],
                                  t_file=entry[1],
                                  t_size=entry[2])

        context["prev_uri"], context["next_uri"] = return_prev_next(
            paths["album_viewing"], paths["webpath"], context["sort_order"])
        context["webpath"] = paths["webpath"]
#        thumbnail.pool.shutdown()
        thumbnail.pool.wait()
        print "\r-------------\r"
        print "Gallery page, elapsed - %s\r" % (time.time() - start_time)
        print "\r-------------\r"
        return HttpResponse(template.render(context, request))


def thumbnails(request):
    """
    Serve the thumbnail resources
    """
    webpath = request.path_info
    album_viewing = configdata["locations"]["albums_path"] +  \
        webpath.replace("/", os.sep)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


def resources(request):
    """
    Serve the resources
    """
    webpath = request.path_info
    album_viewing = configdata["locations"]["resources_path"] +  \
        webpath.replace(r"/resources/", r"/").replace("/", os.sep)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


def galleryitem(request, viewitem):
    """
    Serve the gallery items
    """
    context = {}
    paths = {}
    context["mobile"] = detect_mobile(request)
    request, context = sort_order(request, context)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(paths["item_fs"].lower())

    if "download" in request.GET and "page" not in request.GET:
        return serve(request, os.path.basename(paths["item_fs"]),
                     paths["item_path"])
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails")+r"/"
    if not os.path.exists(paths["item_fs"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    CDL.smart_read(paths["item_path"].lower().strip())
    cached_files, cached_dirs = CDL.return_sorted(
        scan_directory=paths["item_path"],
        sort_by=context["sort_order"], reverse=False)

    listings = []
    for count, dcache in enumerate(cached_dirs + cached_files):
        #               0,          1,          ,2                  , 3
        #   Listings = filename, dcache entry, web tnail path, tnail fs path
        #
        #   4
        #  web path to original
        listings.append((dcache[0].split("/")[0], dcache[1],
                         (paths["web_thumbpath"] +
                          THUMBNAIL.make_tnail_name(filename=dcache[0])["medium"],
                          paths["web_thumbpath"] +
                          THUMBNAIL.make_tnail_name(filename=dcache[0])["large"]),
                         (THUMBNAIL.make_tnail_fsname(
                             dcache[1].fq_filename)["medium"],
                          THUMBNAIL.make_tnail_fsname(
                              dcache[1].fq_filename)["large"]),
                         thumbnail.THUMBNAIL_DB.get(
                             dcache[1].file_extension, "#FFFFFF")))
    chk_list = Paginator(listings, 1)
    template = loader.get_template('frontend/gallery_item.html')
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(request.GET.get("page"))
        context["page"] = request.GET.get("page")
    except PageNotAnInteger:
        for count, fentry in enumerate(cached_files):
            if fentry[1].filename.lower() == paths["item_name"].lower():
                context["page"] = 1+count+len(cached_dirs)
            else:
                context["pagelist"] = chk_list.page(1)
        context["pagelist"] = chk_list.page(context["page"])
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    if "download" in request.GET and "page" in request.GET:
        return serve(request,
                     os.path.basename(
                         context["pagelist"].object_list[0][1].fq_filename),
                     os.path.dirname(
                         context["pagelist"].object_list[0][1].fq_filename))

    context["all_listings"] = listings
    context["current_page"] = context["page"]
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    for entry in listings[fastnumbers.fast_int(context["page"])-1-(context["pagelist"].has_previous() is True):
            fastnumbers.fast_int(context["page"])+(context["pagelist"].has_next() is True)]:
            # context["pagelist"]:
        create_validate_thumb(src_file=entry[1],
                              t_file=entry[3][1-(context["mobile"] is True)],
                              t_size=configdata["configuration"][SIZES[2-(context["mobile"] is True)]])
    thumbnail.pool.wait()
    return HttpResponse(template.render(context, request))


def return_cdl_index(cdl_data, filename):
    """
    Return the index of the archive in the CDL data
    """
    for count, cdl_record in enumerate(cdl_data):
        if cdl_record[0].lower() == filename.lower():
            return count


def viewarchive(request, viewitem):
    """
    Serve archive files
    """
    context = {}
    paths = {}
    request, context = sort_order(request, context)
    if "a_item" in request.GET:
        print "Forwarding to archive_item"
        return archive_item(request, viewitem)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails")+r"/"
    global_listings = read_from_cdl(paths["item_path"],
                                    sort_by=context["sort_order"])
    archive_index = return_cdl_index(global_listings, paths["item_name"])
    tools.assure_path_exists(paths["thumb_path"] + os.sep + paths["item_name"])
    listings = []
    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
    for count, filename in enumerate(global_listings[archive_index][1].
                                     archive_file.listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color

        listings.append((filename,
                         global_listings[archive_index][1].fq_filename,
                         paths["web_thumbpath"] + paths["item_name"] + "/" +
                         THUMBNAIL.make_tnail_name(filename=filename)["small"],
                         THUMBNAIL.make_tnail_fsname(
                             paths["thumb_path"] + "%s%s%s%s" % (
                                 os.sep, paths["item_name"],
                                 os.sep, filename))["small"],
                         thumbnail.THUMBNAIL_DB.get(
                             global_listings[archive_index][1].
                             file_extension, "#FFFFFF"),
                         count+1))
        if os.path.splitext(filename)[1][1:].lower() in thumbnail.THUMBNAIL_DB:
            file_data = archive_file.extract_mem_file(filename)
            if file_data is not None:
                THUMBNAIL.create_thumbnail_from_memory(memory_image=file_data,
                    t_filename=listings[-1][3],
                    t_size=configdata["configuration"]["sm_thumb"])

    context["current_page"] = request.GET.get("page")
    chk_list = Paginator(listings, 30)
    context["page_cnt"] = range(1, chk_list.num_pages+1)
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["all_listings"] = global_listings

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
    thumbnail.pool.wait()
    template = loader.get_template('frontend/archive_gallery.html')
    return HttpResponse(template.render(context, request))


def archive_item(request, viewitem):
    """
    Serve the gallery items
    """
    context = {}
    paths = {}
    context["mobile"] = detect_mobile(request)
    request, context = sort_order(request, context)
    paths["archive_item"] = fastnumbers.fast_int(get_option_value(request,
        "a_item", 1))-1
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/",
                                              os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
#    tnails = thumbnail.Thumbnails()
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails")+r"/"
    global_listings = read_from_cdl(paths["item_path"],
                                    sort_by=context["sort_order"])
    archive_index = return_cdl_index(global_listings, paths["item_name"])
    tools.assure_path_exists(paths["thumb_path"] + os.sep + paths["item_name"])
    listings = []
    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
#    tnails = thumbnail.Thumbnails()
    for count, filename in enumerate(global_listings[archive_index][1].
                                     archive_file.listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color

        listings.append((filename,
                         global_listings[archive_index][1].fq_filename,
                         (paths["web_thumbpath"] + paths["item_name"] + "/" +
                          THUMBNAIL.make_tnail_name(filename=filename)["medium"],
                          paths["web_thumbpath"] + paths["item_name"] + "/" +
                          THUMBNAIL.make_tnail_name(filename=filename)["large"]),
                         (THUMBNAIL.make_tnail_fsname(
                             paths["thumb_path"] + "%s%s%s%s" % (
                                 os.sep, paths["item_name"],
                                 os.sep, filename))["medium"],
                          THUMBNAIL.make_tnail_fsname(
                              paths["thumb_path"] + "%s%s%s%s" % (
                                  os.sep, paths["item_name"],
                                  os.sep, filename))["large"]),
                         thumbnail.THUMBNAIL_DB.get(
                                     global_listings[archive_index][1].
                                     file_extension, "#FFFFFF"),
                         count+1))
    if os.path.splitext(listings[paths["archive_item"]][0])[1][1:].lower()\
            in thumbnail.THUMBNAIL_DB:
        file_data = archive_file.extract_mem_file(\
            listings[paths["archive_item"]][0])
        #print listings[paths["archive_item"]]
        if file_data is not None:
            THUMBNAIL.create_thumbnail_from_memory(memory_image=file_data,
                t_filename=listings[paths["archive_item"]][3][1-(context["mobile"] is True)],\
                t_size=configdata["configuration"][SIZES[1-(context["mobile"] is True)]])

    context["current_page"] = request.GET.get("a_item")
    chk_list = Paginator(listings, 1)
    context["page_cnt"] = range(1, chk_list.num_pages+1)
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["all_listings"] = global_listings

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
    thumbnail.pool.wait()
    template = loader.get_template('frontend/archive_item.html')
#        thumbnail.pool.shutdown()
    return HttpResponse(template.render(context, request))
