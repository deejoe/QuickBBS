"""
Gallery plugin for server
"""
import mimetypes
import os
import os.path

import bread
import common
import directory_caching
import natsort
import ftypes_paths
import tnail_services
import semantic_url
import urllib2

from twisted.web.server import NOT_DONE_YET
from twisted.web import server
from twisted.web.resource import Resource
from twisted.internet import threads

from zope.interface import Interface, Attribute, implements
from twisted.web.server import Session
from twisted.python.components import registerAdapter

SEND_FILE_DEFERRED = True
TNAIL_DEFERRED = True

##############################################################################
class ILoginSessionData(Interface):
    """
    User Session data
    """
    username = Attribute("the users name")
    csrf = Attribute("the csrf token")
    urlref = Attribute("where to go after login")
    sort_order = Attribute("Sort Order")
##############################################################################
class LoginSessionData(object):

    """
    User Session implementation
    """
    implements(ILoginSessionData)

    def __init__(self, session):
        self.username = ""
        self.csrf = ""
        self.urlref = ""
        self.sort_order = 0
registerAdapter(LoginSessionData, Session, ILoginSessionData)
##############################################################################
class Gallery(Resource):

    """
    Log the user out
    """
    isLeaf = True
##############################################################################
    def __init__(self, ctx, env, log):
        """
            The gallery system.

            self.cdl - cached directory listings (see directory_caching)
        """
        self.ctx = ctx
        self.env = env
        self.log = log
        if not os.path.exists(ftypes_paths.locations["albums_root"]):
            print "Creating Albums Folder"
            os.mkdir(ftypes_paths.locations["albums_root"])

        if not os.path.exists(ftypes_paths.locations["thumbnails_root"]):
            print "Creating Thumbnails Folder"
            os.mkdir(ftypes_paths.locations["thumbnails_root"])

        self.gallery_items_per_page = 30
        self.archive_items_per_page = 21
        self.defer_images_after = 9
        self.session_cookie_expiration = 604800  # 7 in seconds days
        self.cdl = directory_caching.Cache()
        self.cdl.files_to_ignore = ftypes_paths.files_to_ignore
        self.cdl.acceptable_extensions = ftypes_paths.image_safe_files
        self.cdl.filter_filenames = common.clean_filename2
        print "Priming the cache for %s, please wait" %\
            ftypes_paths.locations["albums_root"].lower().strip()
        self.cdl.smart_read(
            ftypes_paths.locations["albums_root"].lower().strip())
        print "Pump primed."
        self.semantic = semantic_url.semantic_url(\
            pageitems=self.gallery_items_per_page,
            subpageitems=self.archive_items_per_page)
        Resource.__init__(self)
##############################################################################
    def send_file(self, request, filename):
        """
        Send a file to the web browser

        Optimizing using:

        http://stackoverflow.com/questions/1538617/
                    http-download-very-big-file
        """
        mimetype = mimetypes.guess_type(filename)
        if mimetype != (None, None):
            request.setHeader("content-type", mimetype[0])
            temp = open(filename, 'rb').readlines()
            if SEND_FILE_DEFERRED:
#                self.transport.write(''.join(temp))
                request.write(''.join(temp))
                request.finish()
            else:
                return ''.join(temp)
##############################################################################
    def return_directory_tnail_filename(self, directory_to_use):
        """
        Identify candidate in directory for creating a tnail,
        and then return that filename.
        """
        #
        #   rewrite to use return_directory_contents
        #
        data = self.cdl.return_sort_name(directory_to_use.lower().strip())[0]
        for thumbname in data:
            if thumbname[1].file_extension in ftypes_paths.graphic_file_types:
                return os.sep.join([directory_to_use, thumbname[0]])
        return None
##############################################################################
    def create_directory_tnail(self, dir_record):
        """
        Create a tnail for the directory.  Not contained in tnail
        services, since it needs file system access.
        """
        if dir_record.file_extension == "dir":

            #
            #   This is a folder
            self.cdl.smart_read(dir_record.fq_filename.lower().strip())
            tnail_sourcefile = self.return_directory_tnail_filename(
                dir_record.fq_filename)
            if tnail_sourcefile != None:
                #
                #   tnail has been identified, create tnail
                tnail_target = os.path.split(tnail_sourcefile)[0:-1][0]
                tnail_target = tnail_target.replace("/albums/", "/thumbnails/")

                if not os.path.exists(os.path.dirname(tnail_target)):
                    os.makedirs(os.path.dirname(tnail_target))

                threads.deferToThread(
                    tnail_services.create_thumbnail,
                    fq_filename=tnail_sourcefile,
                    fq_thumbnail=tnail_target,
                    gallery=True,
                    mobile=False)
                return server.NOT_DONE_YET
            else:
                pass
##############################################################################
    def get_directory_offset(self, offset,
                             scan_directory,
                             current_directory):
        """
        Return the next / previous directory name, per offset
        """
        temp = self.cdl.return_current_directory_offset(
            scan_directory=scan_directory.lower(),
            current_directory=current_directory,
            sort_type=self.ctx["sort_order"],
            offset=offset)[1]
        if temp != None:
            return ((common.post_slash(common.pre_slash(scan_directory))\
                     + temp), temp)
        else:
            return (None, None)
##############################################################################
    def set_breadcrumbs_and_title(self):
        """
        Set the Breadcrumbs, and title variables in ctx - dir_nav
        """
        breadcrumbs = bread.Bread(os.path.join(self.ctx["web_path"]))
        breadcrumbs.include_protocol = False
        self.ctx["dir_nav"]["breadcrumbs"] = breadcrumbs.links
        self.ctx["dir_nav"]["title"] = breadcrumbs.crumbs[-1]
##############################################################################
    def set_prev_next_dir(self):
        """
            Set the previous, and next directory values in ctx - dir_nav
        """
        self.ctx["dir_nav"]["prev_dir_url"],\
        self.ctx["dir_nav"]["prev_dir_desc"] = (None, None)
        self.ctx["dir_nav"]["next_dir_url"],\
        self.ctx["dir_nav"]["next_dir_desc"] = (None, None)

        self.ctx["dir_nav"]["prev_dir_url"],\
        self.ctx["dir_nav"]["prev_dir_desc"] = self.get_directory_offset(\
                offset=-1,
                scan_directory=self.ctx["fq_parent_directory"].lower(),
                current_directory=self.ctx["current_directory"][1:])

        self.ctx["dir_nav"]["next_dir_url"],\
        self.ctx["dir_nav"]["next_dir_desc"] = self.get_directory_offset(\
            offset=+1,
            scan_directory=self.ctx["fq_parent_directory"].lower(),
            current_directory=self.ctx["current_directory"][1:])
##############################################################################
    def calc_total_pages(self, gallery=True):
        """
            Set the sidebar / total_item_count variables
        """
        if gallery:
            return (self.ctx["sidebar"]["total_item_count"] /
                    self.gallery_items_per_page) + 1
        else:
            return (self.ctx["sidebar"]["total_item_count"] /
                    self.archive_items_per_page) + 1
##############################################################################
    def display_gallery_page(self):
        """
        Display a index page for a gallery
        """
        self.ctx["dir_nav"] = {}
        self.ctx["gallery"] = {}
        self.ctx["sidebar"] = {}

        self.set_breadcrumbs_and_title()
        self.cdl.smart_read(self.ctx["fq_directory"])
        self.set_prev_next_dir()

        dirs, files = self.return_directory_sorted(
            sort_order=self.ctx["sort_order"],
            directory_path=self.ctx["fq_directory"])

        catalog = dirs + files

        self.ctx["sidebar"]["total_item_count"] = len(catalog)

        self.ctx["gallery"]["current_page"],\
        self.ctx["gallery"]["current_item"] = self.semantic.current_page(),\
                                              self.semantic.current_item()

        self.ctx["gallery"]["current_page"] = semantic_url.norm_page_cnt(
            self.ctx["gallery"]["current_page"],
            self.ctx["sidebar"]["total_item_count"])

        start_offset = (
            self.ctx["gallery"]["current_page"] - 1) *\
                self.gallery_items_per_page

        self.ctx["dlisting"] = catalog[
            start_offset:start_offset + self.gallery_items_per_page]

        self.ctx["sidebar"]["page_count"] = self.calc_total_pages()

        self.ctx["sidebar"]["page_count_loop"] = range(
            1, self.ctx["sidebar"]["page_count"] + 1)

        self.ctx["sidebar"]["current_page"] = self.ctx[
            "gallery"]["current_page"]

        self.ctx["sidebar"]["parent_directory"] = common.pre_slash(
            self.ctx["parent_directory"])

        #   The sidebar parent directory needs a prepending / since we are
        #   using absolute web directories.
        if self.semantic.change_page(offset=+1, nom=True,
                                     max_page_count=\
                                     self.ctx["sidebar"]["page_count"]):
            self.ctx["sidebar"]["next_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["next_page_url"] = None

        self.semantic.revert_to_parsed()

        if self.semantic.change_page(offset=-1, nom=True,
                                     max_page_count=\
                                     self.ctx["sidebar"]["page_count"]):
            self.ctx["sidebar"]["prev_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["prev_page_url"] = None

        self.ctx["gallery"]["textwrap"] = 25 + (not self.ctx["mobile"])*25

        self.ctx["filetypes"] = ftypes_paths.filetype_dict
        self.set_ctx_tnail_sizes()

        self.ctx["gallery"]["body_color"] = 'CCCCFF'

        self.ctx["gallery"]["last_page"] = self.ctx["sidebar"]["page_count"]
        self.ctx["gallery"]["current_directory"] = self.ctx[
            "current_directory"]

        self.ctx["gallery"]["total_item_count"] = len(self.ctx["dlisting"])
        template = self.env.get_template("gallery_listing.html")

        for index in range(0, len(self.ctx["dlisting"])):
            dlist_item = self.ctx["dlisting"][index]
            if dlist_item[1].file_extension == "dir":
                self.create_directory_tnail(dlist_item[1])
            else:
                if self.defer_images_after > index:
                    tnail_services.create_thumbnail_for_file(\
                        ftypes_paths.locations["server_root"],
                        dlist_item[1].fq_filename,
                        dlist_item[1].file_extension,
                        cover=True,
                        gallery=True,
                        mobile=False)
                else:
                    threads.deferToThread(
                        tnail_services.create_thumbnail_for_file,
                        ftypes_paths.locations["server_root"],
                        dlist_item[1].fq_filename,
                        dlist_item[1].file_extension,
                        cover=True,
                        gallery=True,
                        mobile=False)
        return str(template.render(self.ctx))
##############################################################################
    def return_directory_sorted(self,
                                sort_order=0,
                                directory_path=None):
        """
            Connivence method, to help reduce the code duplicateion, and
            multiple if logic checks for the sorting code.
        """
        directory_path = directory_path.lower().strip()
        self.cdl.smart_read(directory_path)
        if sort_order in [0, 1]:
            #   Named Sort - 0, reverse name sort - 1
            files, dirs = self.cdl.return_sort_name(
                scan_directory=directory_path,
                reverse=False)
        elif sort_order in [2, 3]:
            files, dirs = self.cdl.return_sort_lmod(
                scan_directory=directory_path,
                reverse=True)

        elif sort_order in [4, 5]:
            files, dirs = self.cdl.return_sort_ctime(
                scan_directory=directory_path,
                reverse=True)
        return (dirs, files)
##############################################################################
    def display_single_item(self):
        """
        Display a single item from a gallery.
        """
        def calculate_single_item_details(ctx):
            """
            Calculate the current item number for single item view
            """
            self.set_breadcrumbs_and_title()
            ctx["gallery"]["home_path"] = common.pre_slash(\
                self.semantic.return_current_uri_page_only())
            ctx["gallery"]["current_page"],\
            ctx["gallery"]["current_item"] = self.semantic.current_page(),\
                                             self.semantic.current_item()-1

            if ctx["gallery"]["current_page"] == None:
                ctx["gallery"]["current_page"] = 1

            ctx["sidebar"]["current_item"] = \
                self.semantic.current_pi_to_number()-1
            ctx["sidebar"]["current_page"] = ctx["gallery"]["current_page"]

            dirs, files = self.return_directory_sorted(
                sort_order=ctx["sort_order"],
                directory_path=ctx["fq_filename"])
            catalog = (dirs + files)
            ctx["dlisting"] = catalog[ctx["sidebar"]["current_item"]]
            return (ctx, catalog)

        self.ctx["dir_nav"] = {}
        self.ctx["gallery"] = {}
        self.ctx["sidebar"] = {}

        self.ctx["dir_nav"]["prev_dir_url"] = None
        self.ctx["dir_nav"]["prev_dir_desc"] = None
        self.ctx["dir_nav"]["next_dir_url"] = None
        self.ctx["dir_nav"]["next_dir_desc"] = None

        self.ctx, catalog = calculate_single_item_details(self.ctx)
        #
        #   Since the semantic URL is not decoded earlier, there is no way
        #   to identify if this is an archive, or not.  This will dispatch
        #   to archive viewers if necessary.
        if self.ctx["dlisting"][1].file_extension in\
                ftypes_paths.archive_file_types:
            if self.semantic.current_subitem() != None:
                return self.display_archive_single_item()
            else:
                return self.display_archive_page()

        self.ctx["sidebar"]["item_list"] = []

        for cat_item in range(0, len(catalog)):
            page_cnt = cat_item / self.gallery_items_per_page
            file_cnt = (cat_item - (self.gallery_items_per_page * page_cnt))
            if catalog[cat_item][1].filename == "":
                self.ctx["sidebar"]["item_list"].append(
                    (catalog[cat_item][1].directoryname, "",
                     catalog[cat_item][1].directoryname))
            else:
                self.ctx["sidebar"]["item_list"].append(
                    (page_cnt + 1, file_cnt+1, catalog[cat_item][1].filename))

        # adjusting for 0 vs 1 indexs.
        self.ctx["gallery"]["total_item_count"] = len(catalog)
        self.ctx["sidebar"]["total_item_count"] = len(catalog)
        self.ctx["sidebar"]["item_count"] = len(catalog)

        self.ctx["sidebar"]["parent_directory"] = \
            common.pre_slash((self.ctx["parent_directory"]))
        #   The sidebar parent directory needs a prepending / since we are
        #   using absolute web directories.

        self.ctx["sidebar"]["page_count"] = self.calc_total_pages()

        if self.semantic.change_item(offset=+1, nom=True,
                                     max_item_count=\
                                     self.gallery_items_per_page):
            self.ctx["sidebar"]["next_page_url"] = common.pre_slash(\
                self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["next_page_url"] = None

        self.semantic.revert_to_parsed()
        if self.semantic.change_item(offset=-1, nom=True,
                                     max_item_count=\
                                     self.gallery_items_per_page):
            self.ctx["sidebar"]["prev_page_url"] = common.pre_slash(\
                self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["prev_page_url"] = None

        self.ctx["gallery"]["textwrap"] = 25 + (not self.ctx["mobile"])*25
        #   if mobile, add 25 to textwrap

        self.ctx["filetypes"] = ftypes_paths.filetype_dict

        self.set_ctx_tnail_sizes()
        self.ctx["gallery"]["body_color"] = 'CCCCFF'

        self.ctx["gallery"]["last_page"] = self.ctx["sidebar"]["item_count"]
        self.ctx["gallery"]["current_directory"] = self.ctx[
            "current_directory"]

        template = self.env.get_template("single_item_view.html")

        preview = catalog[self.ctx["sidebar"]["current_item"]]
        tnail_services.create_thumbnail_for_file(
            ftypes_paths.locations["server_root"],
            preview[1].fq_filename,
            preview[1].file_extension,
            cover=False,
            gallery=False,
            mobile=self.ctx['mobile'])

        return str(template.render(self.ctx))
##############################################################################
    def render_GET(self, request):
        """
        Process the Gallery Request
        """
        session = request.getSession()
        login = ILoginSessionData(session)
        if not login.username or login.username == "":
            # this should store the current path, render the login page, and
            # finally redirect back here
            login.urlref = request.path
            request.redirect("/login")
            request.finish()
            return NOT_DONE_YET

        request_list = request.prepath + request.postpath
        if request.args.has_key("sort"):
            self.ctx["sort_order"] = int(request.args["sort"][0])
            login.sort_order = int(request.args["sort"][0])
        else:
            self.ctx['sort_order'] = login.sort_order

        self.semantic.parse_uri(request_list)
        self.ctx['mobile'] = request.getHeader(
            "User-Agent").find("Mobile") != -1
        self.ctx['username'] = login.username


        request.postpath = self.semantic.current_dir()
        request_string = '/'.join(request_list)

        self.ctx["request_string"] = urllib2.unquote(\
            common.pre_slash(request_string))

        self.ctx["parent_directory"] = "/".join(\
            request.postpath.split("/")[0:-1])
        self.ctx["fq_parent_directory"] = \
            os.sep.join([ftypes_paths.locations["albums_root"],
                         self.ctx["request_string"]][0:-1])

        print os.path.abspath(
#                os.sep.join([ftypes_paths.locations["server_root"],
                os.sep.join([ftypes_paths.locations["albums_root"],
                             self.ctx["request_string"]]))
        if os.path.isfile(os.path.abspath(
#                os.sep.join([ftypes_paths.locations["server_root"],
                os.sep.join([ftypes_paths.locations["albums_root"],
                             self.ctx["request_string"]]))):
            self.ctx["fq_filename"] = os.path.abspath(
#                os.sep.join([ftypes_paths.locations["server_root"],
                os.sep.join([ftypes_paths.locations["albums_root"],
                             self.ctx["request_string"]]))
            #
            #   It's a file to be sent
            #
            if SEND_FILE_DEFERRED:
                threads.deferToThread(
                    self.send_file, request, self.ctx["fq_filename"])
                return NOT_DONE_YET
            else:
                return self.send_file(request, self.ctx["fq_filename"])

        self.ctx["fq_directory"] = os.path.abspath(
#            os.sep.join([ftypes_paths.locations["server_root"],
            os.sep.join([ftypes_paths.locations["albums_root"],
                         self.ctx["request_string"]]))

        self.ctx["current_directory"] = common.pre_slash(\
            request.postpath.split("/")[-1])

        self.ctx["web_path"] = common.pre_slash(
            common.post_slash((self.ctx["request_string"])))

        self.ctx["thumbnail_path"] = self.ctx["web_path"].replace(
            "albums/", "thumbnails/")

        if not self.semantic.current_item() in [0, None]:
            #
            #   We are displaying a single item view
            #
            self.ctx["fq_filename"] = os.path.abspath(
#                os.sep.join([ftypes_paths.locations["server_root"],
                os.sep.join([ftypes_paths.locations["albums_root"],
                             self.ctx["request_string"]]))
#            print "displaying single file - %s" % self.ctx["fq_filename"]
            return self.display_single_item()
        else:
#            print "displaying Gallery - %s" % self.ctx["current_directory"]
            #
            #   We are displaying a gallery
            #
            return self.display_gallery_page()

##############################################################################
    def display_archive_page(self):
        """
Display a index page for a archive gallery


Typical URL - 127.0.0.1:8888/albums/1/2 - Page 1 Item 2

Archive URL - 127.0.0.1:8888/albums/1/11 - The archive is what is
            being pointed at.

Possible fixes - make a switch? - Cancels the advantage of the SURL

Most likely is to extend the semantic url to add a 3rd layer
which would be sub-page, and sub-item.

127.0.0.1:8888/albums/1/11/55/3
                    - Page 1, Item 11 (archive)
                    - Archive Page - 55, Archive Item 3
* Page
* Item
* subpage   (Archives)
* subitem   (Archives)

archive_items_per_page
        """
        self.ctx["dir_nav"] = {}
        self.ctx["gallery"] = {}
        self.ctx["sidebar"] = {}

        self.set_breadcrumbs_and_title()

        self.ctx["thumbnail_path"] = self.ctx["web_path"].replace(
            "albums/", "thumbnails/") + self.ctx["dlisting"][0] + os.sep

        self.ctx["dir_nav"]["prev_dir_url"],\
            self.ctx["dir_nav"]["prev_dir_desc"] = (None, None)
        self.ctx["dir_nav"]["next_dir_url"],\
            self.ctx["dir_nav"]["next_dir_desc"] = (None, None)

        filelistings_ptr = tnail_services.setup_archive_processing(\
            self.ctx["dlisting"][1].file_extension)[0]

        full_comic_list = filelistings_ptr(self.ctx["dlisting"][1].fq_filename)
        full_comic_list = natsort.natsort(full_comic_list)

        self.ctx["gallery"]["total_item_count"] = len(full_comic_list)
        self.ctx["sidebar"]["total_item_count"] = len(full_comic_list)
        self.ctx["sidebar"]["item_count"] = len(full_comic_list)

        self.ctx["sidebar"]["page_count"] = self.calc_total_pages(gallery=False)

        self.semantic.revert_to_parsed()
        if self.semantic.change_subpage(offset=+1, nom=True,
                                        max_page_count=\
                                        self.archive_items_per_page):
            self.ctx["sidebar"]["next_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["next_page_url"] = None

        self.semantic.revert_to_parsed()

        if self.semantic.change_subpage(offset=-1, nom=True,
                                        max_page_count=\
                                        self.archive_items_per_page):
            self.ctx["sidebar"]["prev_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["prev_page_url"] = None

        self.semantic.revert_to_parsed()

        comic_list = full_comic_list[self.semantic.current_spi_to_number():\
                self.semantic.current_spi_to_number() + \
                self.archive_items_per_page]

        for archive_pages in range(0, len(comic_list)):
            if self.defer_images_after > archive_pages:
                tnail_services.create_thumbnail_for_file(\
                    ftypes_paths.locations["server_root"],
                    self.ctx["dlisting"][1].fq_filename,
                    self.ctx["dlisting"][1].file_extension,
                    cover=False,
                    gallery=True,
                    mobile=False,
                    filename=comic_list[archive_pages])
            else:
                threads.deferToThread(\
                    tnail_services.create_thumbnail_for_file,
                    ftypes_paths.locations["server_root"],
                    self.ctx["dlisting"][1].fq_filename,
                    self.ctx["dlisting"][1].file_extension,
                    cover=False,
                    gallery=True,
                    mobile=False,
                    filename=comic_list[archive_pages])

        self.ctx["sidebar"]["total_item_count"] = len(comic_list)

        self.ctx["gallery"]["current_page"],\
        self.ctx["gallery"]["current_item"] = self.semantic.current_page(),\
                                              self.semantic.current_item()

        self.ctx["gallery"]["current_page"] = semantic_url.norm_page_cnt(
            self.ctx["gallery"]["current_page"],
            self.ctx["sidebar"]["page_count"])

        self.ctx["gallery"]["current_subpage"],\
            self.ctx["gallery"]["current_subitem"] = \
                self.semantic.current_subpage(),\
                self.semantic.current_subitem()

        self.ctx["gallery"]["current_subpage"] = semantic_url.norm_page_cnt(
            self.ctx["gallery"]["current_subpage"],
            self.ctx["sidebar"]["page_count"])

        self.ctx["sidebar"]["page_count_loop"] = range(
            1, self.ctx["sidebar"]["page_count"] + 1)

        self.ctx["sidebar"]["current_page"] = self.ctx[
            "gallery"]["current_page"]

        self.ctx["sidebar"]["parent_directory"] = common.pre_slash(\
            self.semantic.return_current_uri_subpage())

        #   The sidebar parent directory needs a prepending / since we are
        #   using absolute web directories.

        self.ctx["gallery"]["textwrap"] = 25 + (not self.ctx["mobile"])*25
        #   if mobile, add 25 to textwrap

        self.ctx["filetypes"] = ftypes_paths.filetype_dict
        self.set_ctx_tnail_sizes()

        self.ctx["gallery"]["body_color"] = 'CCCCFF'

        self.ctx["gallery"]["last_page"] = self.ctx["sidebar"]["page_count"]
        self.ctx["gallery"]["current_directory"] = self.ctx[
            "current_directory"]

        self.ctx["archive_listings"] = []
        for a_listing in comic_list:
            self.ctx["archive_listings"].append(os.path.split(a_listing)[1])
        self.ctx["gallery"]["total_item_count"] = len(self.ctx["dlisting"])
        template = self.env.get_template("archive_listing.html")

        return str(template.render(self.ctx))
##############################################################################
    def set_ctx_tnail_sizes(self):
        """
        Set the thumbnail size values for CTX / gallery
        """
        self.ctx["gallery"]["small"] = tnail_services.thumbnails["small"][0]
        self.ctx["gallery"]["mobile"] = tnail_services.thumbnails["mobile"][0]
        self.ctx["gallery"]["large"] = tnail_services.thumbnails["large"][0]
##############################################################################
    def display_archive_single_item(self):
        """
        Display a single item from a gallery.
        """
        self.ctx["dir_nav"] = {}
        self.ctx["gallery"] = {}
        self.ctx["sidebar"] = {}
        print "Displaying single item"
        self.set_breadcrumbs_and_title()

        self.ctx["thumbnail_path"] = self.ctx["web_path"].replace(
            "albums/", "thumbnails/") + self.ctx["dlisting"][0] + os.sep

        self.ctx["dir_nav"]["prev_dir_url"],\
            self.ctx["dir_nav"]["prev_dir_desc"] = (None, None)
        self.ctx["dir_nav"]["next_dir_url"],\
            self.ctx["dir_nav"]["next_dir_desc"] = (None, None)

        filelistings_ptr = tnail_services.setup_archive_processing(\
            self.ctx["dlisting"][1].file_extension)[0]

        full_comic_list = filelistings_ptr(self.ctx["dlisting"][1].fq_filename)
        full_comic_list = natsort.natsort(full_comic_list)

        self.ctx["gallery"]["total_item_count"] = len(full_comic_list)
        self.ctx["sidebar"]["total_item_count"] = len(full_comic_list)
        self.ctx["sidebar"]["item_count"] = len(full_comic_list)

        self.ctx["sidebar"]["page_count"] = self.calc_total_pages(gallery=False)

        self.semantic.revert_to_parsed()
        if self.semantic.change_subitem(offset=+1, nom=True,
                                        max_item_count=\
                                        self.archive_items_per_page):
            self.ctx["sidebar"]["next_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["next_page_url"] = None

        self.semantic.revert_to_parsed()

        if self.semantic.change_subitem(offset=-1, nom=True,
                                        max_item_count=\
                                        self.archive_items_per_page):
            self.ctx["sidebar"]["prev_page_url"] = \
                common.pre_slash(self.semantic.return_current_uri())
        else:
            self.ctx["sidebar"]["prev_page_url"] = None

        self.semantic.revert_to_parsed()

        comic_list = full_comic_list[self.semantic.current_spi_to_number()-1]
        tnail_services.create_thumbnail_for_file(\
            ftypes_paths.locations["server_root"],
            self.ctx["dlisting"][1].fq_filename,
            self.ctx["dlisting"][1].file_extension,
            cover=False,
            gallery=False,
            mobile=self.ctx["mobile"],
            filename=comic_list)

        self.ctx["sidebar"]["total_item_count"] = len(comic_list)

        self.ctx["gallery"]["current_page"],\
        self.ctx["gallery"]["current_item"] = self.semantic.current_page(),\
                                              self.semantic.current_item()

        self.ctx["gallery"]["current_page"] = semantic_url.norm_page_cnt(
            self.ctx["gallery"]["current_page"],
            self.ctx["sidebar"]["total_item_count"])

        self.ctx["gallery"]["current_subpage"],\
            self.ctx["gallery"]["current_subitem"] = \
                self.semantic.current_subpage(),\
                self.semantic.current_subitem()

        self.ctx["gallery"]["current_subpage"] = semantic_url.norm_page_cnt(
            self.ctx["gallery"]["current_subpage"],
            self.ctx["sidebar"]["page_count"])

        self.ctx["sidebar"]["page_count_loop"] = range(
            1, self.ctx["sidebar"]["page_count"] + 1)

        self.ctx["sidebar"]["current_page"] = self.ctx[
            "gallery"]["current_page"]

        self.ctx["sidebar"]["parent_directory"] = common.pre_slash(\
            self.semantic.return_current_uri_subpage())

        #   The sidebar parent directory needs a prepending / since we are
        #   using absolute web directories.

        self.ctx["gallery"]["textwrap"] = 25 + (not self.ctx["mobile"])*25
        #   if mobile, add 25 to textwrap

        self.ctx["filetypes"] = ftypes_paths.filetype_dict
        self.set_ctx_tnail_sizes()

        self.ctx["gallery"]["body_color"] = 'CCCCFF'

        self.ctx["gallery"]["last_page"] = self.ctx["sidebar"]["page_count"]

        self.ctx["gallery"]["current_directory"] = self.ctx[
            "current_directory"]

        self.ctx["archive_listings"] = []
        #for a_listing in comic_list:
        #    self.ctx["archive_listings"].append(os.path.split(a_listing)[1])
        self.ctx["archive_listings"].append([os.path.split(comic_list)[1],
                                             os.path.splitext(
                                                 comic_list)[1][1:].lower()])
        self.ctx["gallery"]["total_item_count"] = len(self.ctx["dlisting"])
        template = self.env.get_template("archive_item_view.html")

        return str(template.render(self.ctx))