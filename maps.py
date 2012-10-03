#!/usr/bin/env python
# -*- coding: utf-8 -*-

## @package maps
# This is the Main Window

import os
import re
import sys
import time
import signal
import gobject
import gmapcatcher.mapGPS as mapGPS
import gmapcatcher.mapUtils as mapUtils
import gmapcatcher.widgets.mapPixbuf as mapPixbuf

from gmapcatcher.mapConst import *
from gmapcatcher.widgets.mapTools import mapTools
from gmapcatcher.gtkThread import gui_callback, webbrowser_open
from gmapcatcher.mapConf import MapConf
from gmapcatcher.mapMark import MyMarkers
from gmapcatcher.mapUpdate import CheckForUpdates
from gmapcatcher.mapServices import MapServ
from gmapcatcher.mapDownloader import MapDownloader
from gmapcatcher.xmlUtils import kml_to_markers
from gmapcatcher.widgets.DLWindow import DLWindow
from gmapcatcher.widgets.EXWindow import EXWindow
from gmapcatcher.widgets.gpsWindow import gpsWindow
from gmapcatcher.widgets.trackWindow import trackWindow
from gmapcatcher.widgets.customMsgBox import user_confirm, error_msg
from gmapcatcher.widgets.customWidgets import gtk, gtk_menu, myToolTip, myFrame, lbl, legal_warning, ProgressBar, SpinBtn, FileChooser
from gmapcatcher.widgets.widDrawingArea import DrawingArea
from gmapcatcher.widgets.widComboBoxLayer import ComboBoxLayer
from gmapcatcher.widgets.widComboBoxEntry import ComboBoxEntry
from gmapcatcher.widgets.widStatusBar import StatusBar
from gmapcatcher.widgets.widCredits import OurCredits


class MainWindow(gtk.Window):

    gps = None
    update = None
    myPointer = None
    reCenter_gps = False
    showMarkers = True
    tPoint = {}
    gps_idle_time = 0
    # Variables for Ruler - F7 to activate/deactivate
    Ruler = 0
    total_dist = 0.00
    map_min_zoom = MAP_MIN_ZOOM_LEVEL
    map_max_zoom = MAP_MAX_ZOOM_LEVEL - 1

    ## Get the zoom level from the scale
    def get_zoom(self):
        return int(self.scale.get_value())

    ## Handles the events in the Tools buttons
    def tools_button_event(self, w, event):
        if event.type == gtk.gdk.BUTTON_PRESS:
            w.popup(None, None, None, 1, event.time)
        elif event.type == gtk.gdk.KEY_PRESS and \
             event.keyval in [65293, 32]:
            self.menu_tools(None, TOOLS_MENU[0])

    ## Search for the location in the Entry box
    def confirm_clicked(self, button):
        location = self.entry.get_text()
        if (0 == len(location)):
            error_msg(self, "Need location")
            self.entry.grab_focus()
            return
        if (location == ComboBoxEntry.DEFAULT_TEXT):
            self.combo.clean_entry()
            return
        p = re.compile('(?:lat)?(?:itude)?[ ]*=?[ ]*(-?\d+\.?\d*)[ ]*,[ ]*(?:lon)?g?(?:itude)?[ ]*=?[ ]*(-?\d+\.?\d*).*', re.IGNORECASE)
        coords = p.search(location)
        # nb needs 0.-- for coords 0 < |coord| < 1
        try:
            latitude = float(coords.group(1))
            longitude = float(coords.group(2))
        except:
            longitude = 0
            latitude = -100
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            coord = (latitude, longitude, self.get_zoom())
        else:
            locations = self.ctx_map.get_locations()
            if (not location in locations.keys()):
                if self.cb_offline.get_active():
                    if error_msg(self, "Offline mode, cannot do search!" +
                                "      Would you like to get online?",
                                gtk.BUTTONS_YES_NO) != gtk.RESPONSE_YES:
                        self.combo.combo_popup()
                        return
                self.cb_offline.set_active(False)

                location = self.ctx_map.search_location(location)
                if (location[:6] == "error="):
                    error_msg(self, location[6:])
                    self.entry.grab_focus()
                    return

                self.entry.set_text(location)
                self.combo.set_completion(self.ctx_map, self.confirm_clicked, self.conf)
                locations = self.ctx_map.get_locations()
            coord = locations[unicode(location)]

        self.drawing_area.center = mapUtils.coord_to_tile(coord)
        self.scale.set_value(coord[2])
        self.do_zoom(coord[2], True)

    ## Handles the click in the offline check box
    def offline_clicked(self, w):
        self.drawing_area.repaint()
        if not self.cb_offline.get_active():
            self.do_check_for_updates()

    ## Start checking if there is an update
    def do_check_for_updates(self):
        if self.conf.check_for_updates and (self.update is None):
            # 3 seconds delay before starting the check
            self.update = CheckForUpdates(3, self.conf.version_url)

    ## Handles the change in the GPS combo box
    def gps_changed(self, w):
        if self.gps:
            self.gps.set_mode(w.get_active())
            self.drawing_area.repaint()

    ## Handles the change in the combo box Layer(Map, Sat.. )
    def layer_changed(self, w):
        index = w.get_active()
        cmb_model = self.cmb_layer.get_model()
        self.conf.map_service = MAP_SERVERS[cmb_model[index][1]]
        self.layer = cmb_model[index][2]
        self.ctx_map.tile_repository.set_repository_path(self.conf.init_path)
        if self.visual_dlconfig.get('active', False) and not self.check_bulk_down():
            self.visual_dlconfig['active'] = False
        if self.gps and not self.gps_warning():
            self.gps.stop_all()
            self.gps = None
        self.refresh()

    ## Combo box dispatches operation and returns to default position - Operations - 1st item
    def on_operations_changed(self, w, index):
        if index == 0:
            self.download_clicked(w)
        elif index == 1:
            self.export_clicked(w)
        elif index == 2:
            self.track_control_clicked(w)
        elif index == 3:
            self.gps_window_clicked(w)

    def download_clicked(self, w, pointer=None):
        rect = self.drawing_area.get_allocation()
        if (pointer is None):
            tile = self.drawing_area.center
        else:
            tile = mapUtils.pointer_to_tile(
                rect, pointer, self.drawing_area.center, self.get_zoom()
            )

        coord = mapUtils.tile_to_coord(tile, self.get_zoom())
        km_px = mapUtils.km_per_pixel(coord)
        dlw = DLWindow(coord, km_px * rect.width, km_px * rect.height,
                        self.layer, self.conf)
        dlw.show()

    def export_clicked(self, w, pointer=None):
        rect = self.drawing_area.get_allocation()
        if (pointer is None):
            tile = self.drawing_area.center
        else:
            tile = mapUtils.pointer_to_tile(
                rect, pointer, self.drawing_area.center, self.get_zoom()
            )

        coord = mapUtils.tile_to_coord(tile, self.get_zoom())
        km_px = mapUtils.km_per_pixel(coord)

        exw = EXWindow(self.ctx_map, coord, km_px * rect.width, km_px * rect.height,
                    self.layer, self.conf)
        exw.show()

    def track_control_clicked(self, w=None, pointer=None):
        if not self.trackw:
            self.trackw = trackWindow(self)
            self.trackw.show()
        else:
            self.trackw.update_widgets()
            self.trackw.present()

    def gps_window_clicked(self, w=None, pointer=None):
        if not self.gpsw:
            self.gpsw = gpsWindow(self)
            self.gpsw.show()
        else:
            self.gpsw.present()

    def visual_download(self):
        if self.visual_dlconfig.get('active', False):
            force_update = self.cb_forceupdate.get_active()
            confzl = self.visual_dlconfig.get('zl', -2)
            thezl = self.get_zoom()
            sz = self.visual_dlconfig.get('sz', 4)
            rect = self.drawing_area.get_allocation()

            coord = mapUtils.tile_to_coord(self.drawing_area.center, thezl)
            km_px = mapUtils.km_per_pixel(coord)

            self.visual_dlconfig['downloader'].bulk_download(
                        coord, (thezl - 1, thezl + confzl),
                        km_px * rect.width / sz, km_px * rect.height / sz,
                        self.layer, gui_callback(self.visualdl_cb),
                        self.visualdl_update, force_update, self.conf)
            self.visualdl_update()

    def check_bulk_down(self):
        if self.conf.map_service in NO_BULK_DOWN:
            return legal_warning(self, self.conf.map_service, "bulk downloading")
        return True

    ## Called when new coordinates are obtained from the GPS
    def gps_callback(self):
        if self.gps and self.gps.gpsfix:
            if self.gps.gpsfix.mode != MODE_NO_FIX and self.gps.gpsfix.latitude and self.gps.gpsfix.longitude:
                zl = self.get_zoom()
                tile = mapUtils.coord_to_tile((self.gps.gpsfix.latitude, self.gps.gpsfix.longitude, zl))
                self.gps_valid = True
                # The map should be centered around a new GPS location
                if not self.Ruler and (self.gps.mode == GPS_CENTER or self.reCenter_gps):
                    self.reCenter_gps = False
                    self.drawing_area.center = tile
                # The map should be moved only to keep GPS location on the screen
                elif self.gps.mode == GPS_ON_SCREEN and not self.Ruler:
                    rect = self.drawing_area.get_allocation()
                    xy = mapUtils.tile_coord_to_screen(
                        (tile[0][0], tile[0][1], zl), rect, self.drawing_area.center)
                    if xy:
                        for x, y in xy:
                            x = x + tile[1][0]
                            y = y + tile[1][1]
                            if not(0 < x < rect.width) or not(0 < y < rect.height):
                                self.drawing_area.center = tile
                            else:
                                if GPS_IMG_SIZE[0] > x:
                                    self.drawing_area.da_jump(1, zl, True)
                                elif x > rect.width - GPS_IMG_SIZE[0]:
                                    self.drawing_area.da_jump(3, zl, True)
                                elif GPS_IMG_SIZE[1] > y:
                                    self.drawing_area.da_jump(2, zl, True)
                                elif y > rect.height - GPS_IMG_SIZE[1]:
                                    self.drawing_area.da_jump(4, zl, True)
                    else:
                        self.drawing_area.center = tile
                # GPS update timeout, recenter GPS only after 3 sec idle
                elif self.gps.mode == GPS_TIMEOUT and not self.Ruler:
                    if (time.time() - self.gps_idle_time) > 3:
                        self.drawing_area.center = tile

                self.drawing_area.repaint()
                # Update the status bar with the GPS Coordinates
                if self.conf.statusbar_type == STATUS_GPS and not self.Ruler:
                    self.status_bar.coordinates(self.gps.gpsfix.latitude, self.gps.gpsfix.longitude)
            else:
                self.gps_invalid()
        else:
            self.gps_invalid()

    def gps_invalid(self):
        if self.gps_valid:
            self.gps_valid = False
            self.drawing_area.repaint()
            if self.conf.statusbar_type == STATUS_GPS and not self.Ruler:
                self.status_bar.text('INVALID DATA FROM GPS')

    ## Creates a comboBox that will contain the locations
    def __create_combo_box(self):
        combo = ComboBoxEntry(self.confirm_clicked, self.conf)
        self.entry = combo.child
        return combo

    def operations_sub_menu(self):
        importm = gtk.MenuItem("Operations")
        imenu = gtk.Menu()
        SUB_MENU = ["Download", "Export map", "Track control", "GPS window"]
        for i in range(len(SUB_MENU)):
            menu_item = gtk.MenuItem(SUB_MENU[i])
            menu_item.connect('activate', self.on_operations_changed, i)
            imenu.append(menu_item)
        importm.set_submenu(imenu)
        importm.show_all()
        return importm

    ## Creates the box that packs the comboBox & buttons
    def __create_upper_box(self):
        hbox = gtk.HBox(False, 5)

        gtk.stock_add([(gtk.STOCK_PREFERENCES, "", 0, 0, "")])
        button = gtk.Button(stock=gtk.STOCK_PREFERENCES)
        button.set_size_request(34, -1)
        menu = gtk_menu(TOOLS_MENU, self.menu_tools)
        menu.prepend(self.operations_sub_menu())

        self.visual_dltool = gtk.CheckMenuItem(TOOLS_MENU_PLUS_VISUAL_DL)
        menu.append(self.visual_dltool)
        self.visual_dltool.connect('toggled', self.visual_dltool_toggled)
        self.visual_dltool.show()
        temp = gtk.MenuItem()
        menu.append(temp)
        temp.show()
        self.credits_menuitem = gtk.MenuItem(TOOLS_MENU_PLUS_CREDITS)
        menu.append(self.credits_menuitem)
        self.credits_menuitem.connect('activate', self.view_credits)
        self.credits_menuitem.show()
        button.connect_object("event", self.tools_button_event, menu)
        button.props.has_tooltip = True
        button.connect("query-tooltip", myToolTip, "Tools",
                    "Set of tools to customise GMapCatcher", "marker.png")
        hbox.pack_start(button, False)

        self.combo = self.__create_combo_box()
        hbox.pack_start(self.combo)

        bbox = gtk.HButtonBox()
        button_go = gtk.Button(stock='gtk-ok')
        button_go.connect('clicked', self.confirm_clicked)
        bbox.add(button_go)

        hbox.pack_start(bbox, False, True, 15)
        return hbox

    ## Creates the box with the CheckButtons
    def __create_check_buttons(self):
        hbox = gtk.HBox(False, 10)

        self.cb_offline = gtk.CheckButton("Offlin_e")
        self.cb_offline.set_active(True)
        self.cb_offline.connect('clicked', self.offline_clicked)
        hbox.pack_start(self.cb_offline)

        self.cb_forceupdate = gtk.CheckButton("_Force update")
        self.cb_forceupdate.set_active(False)
        hbox.pack_start(self.cb_forceupdate)

        bbox = gtk.HBox(False, 0)
        cmb_gps = gtk.combo_box_new_text()
        for w in GPS_NAMES:
            cmb_gps.append_text(w)
        cmb_gps.set_active(self.conf.gps_mode)
        cmb_gps.connect('changed', self.gps_changed)
        bbox.pack_start(cmb_gps, False, False, 0)
        self.cmb_gps = cmb_gps
        self.update_cmb_gps()

        self.cmb_layer_container = gtk.HBox()
        self.cmb_layer = ComboBoxLayer(self.conf)
        self.cmb_layer.connect('changed', self.layer_changed)
        self.cmb_layer_container.pack_start(self.cmb_layer)

        bbox.pack_start(self.cmb_layer_container, False, False, 0)
        hbox.add(bbox)
        return hbox

    #Show or hide the gps combo depending on type
    def update_cmb_gps(self):
        if (self.conf.gps_type > TYPE_OFF):
            self.cmb_gps.show()
        else:
            self.cmb_gps.hide()

    def __create_top_paned(self):
        vbox = gtk.VBox(False, 5)
        vbox.set_border_width(5)
        vbox.pack_start(self.__create_upper_box())
        vbox.pack_start(self.__create_check_buttons())
        vbox.set_size_request(-1, 89)
        return myFrame(" Query ", vbox, 0)

    def __create_export_paned(self):
        vboxCoord = gtk.VBox(False, 5)
        vboxCoord.set_border_width(10)

        self.entryUpperLeft = gtk.Entry()
        self.entryUpperLeft.connect("key-release-event", self.update_export)
        self.entryLowerRight = gtk.Entry()
        self.entryLowerRight.connect("key-release-event", self.update_export)

        hbox = gtk.HBox(False)
        vbox = gtk.VBox(False, 5)
        vbox.pack_start(lbl("  Upper Left: "))
        vbox.pack_start(lbl(" Lower Right: "))
        hbox.pack_start(vbox, False, True)
        vbox = gtk.VBox(False, 5)
        vbox.pack_start(self.entryUpperLeft)
        vbox.pack_start(self.entryLowerRight)
        hbox.pack_start(vbox)
        vboxCoord.pack_start(myFrame(" Corners' coordinates ", hbox))

        vboxInput = gtk.VBox(False, 5)
        vboxInput.set_border_width(10)
        vbox = gtk.VBox(False, 20)
        vbox.set_border_width(10)
        hboxSize = gtk.HBox(False, 20)
        hbox = gtk.HBox(False, 5)
        hbox.pack_start(lbl("Width / Height: "), False, True)
        self.sbWidth = SpinBtn(TILES_WIDTH * 4, TILES_WIDTH, 99999, TILES_WIDTH, 5)
        self.sbWidth.connect("value-changed", self.update_export)
        hbox.pack_start(self.sbWidth, False, True)
        hbox.pack_start(lbl("/"), False, True)
        self.sbHeight = SpinBtn(TILES_HEIGHT * 3, TILES_HEIGHT, 99999, TILES_HEIGHT, 5)
        self.sbHeight.connect("value-changed", self.update_export)
        hbox.pack_start(self.sbHeight, False, True)
        hboxSize.pack_start(hbox)
        vbox.pack_start(hboxSize)

        hboxZoom = gtk.HBox(False, 5)
        hboxZoom.pack_start(lbl("    Zoom Level: "), False, True)
        self.expZoom = SpinBtn(self.get_zoom())
        self.expZoom.connect("value-changed", self.update_export)
        hboxZoom.pack_start(self.expZoom, False, True)
        vbox.pack_start(hboxZoom)

        button = gtk.Button(stock='gtk-ok')
        button.connect('clicked', self.do_export)

        hboxInput = gtk.HBox(False, 5)
        hboxInput.pack_start(vbox)
        bbox = gtk.HButtonBox()
        bbox.add(button)
        hboxInput.pack_start(bbox)
        vboxInput.pack_start(myFrame(" Image settings ", hboxInput))

        self.export_box = gtk.HBox(False, 5)
        self.export_box.pack_start(vboxCoord)
        self.export_box.pack_start(vboxInput)
        self.export_pbar = ProgressBar(" Exporting... ")
        hbox = gtk.HBox(False, 5)
        hbox.pack_start(self.export_box)
        hbox.pack_start(self.export_pbar)

        return myFrame(" Export map to PNG image ", hbox)

    def __create_left_paned(self, conf):
        scale = gtk.VScale()
        scale.set_property("update-policy", gtk.UPDATE_DISCONTINUOUS)
        scale.set_size_request(30, -1)
        scale.set_increments(1, 1)
        scale.set_digits(0)
        scale.set_range(self.map_min_zoom, self.map_max_zoom)
        scale.set_value(conf.init_zoom)
        scale.connect("change-value", self.scale_change_value)
        scale.show()
        self.scale = scale
        return scale

    def __create_right_paned(self):
        da = DrawingArea()
        self.drawing_area = da
        da.connect("expose-event", self.expose_cb)

        da.add_events(gtk.gdk.SCROLL_MASK)
        da.connect("scroll-event", self.scroll_cb)

        da.add_events(gtk.gdk.BUTTON1_MOTION_MASK)
        da.add_events(gtk.gdk.POINTER_MOTION_MASK)
        da.connect('motion-notify-event', self.da_motion)

        menu = gtk_menu(DA_MENU, self.menu_item_response)
        da.connect_object("event", self.da_click_events, menu)

        return self.drawing_area

    def scale_change_value(self, therange, scroll, value):
        self.do_zoom(int(round(value)))

    ## Zoom to the given pointer
    def do_zoom(self, zoom, doForce=False, dPointer=False):
        if (self.map_min_zoom <= zoom <= (self.map_max_zoom)):
            self.drawing_area.do_scale(
                zoom, self.get_zoom(), doForce, dPointer
            )
            self.scale.set_value(zoom)
            self.update_export()
            self.gps_idle_time = time.time()

    def menu_tools(self, w, strName):
        for intPos in range(len(TOOLS_MENU)):
            if strName.startswith(TOOLS_MENU[intPos]):
                if not self.settingsw:
                    self.settingsw = mapTools(self, intPos)
                else:
                    self.settingsw.myNotebook.set_current_page(intPos)
                    self.settingsw.present()
                return True

    ## All the actions for the menu items
    def menu_item_response(self, w, strName):
        if strName == DA_MENU[ZOOM_IN]:
            self.do_zoom(self.get_zoom() - 1, True, self.myPointer)
        elif strName == DA_MENU[ZOOM_OUT]:
            self.do_zoom(self.get_zoom() + 1, True, self.myPointer)
        elif strName == DA_MENU[CENTER_MAP]:
            self.do_zoom(self.get_zoom(), True, self.myPointer)
        elif strName == DA_MENU[RESET]:
            self.do_zoom(self.map_max_zoom)
        elif strName == DA_MENU[BATCH_DOWN]:
            self.download_clicked(w, self.myPointer)
        elif strName == DA_MENU[EXPORT_MAP]:
            self.show_export(self.myPointer)
        elif strName == DA_MENU[ADD_MARKER]:
            self.add_marker(self.myPointer)
        elif strName == DA_MENU[MOUSE_LOCATION]:
            self.mouse_location(self.myPointer)
        elif strName == DA_MENU[GPS_LOCATION]:
            self.gps_location()

    ## utility function screen location of pointer to world coord
    def pointer_to_world_coord(self, pointer=None):
        return mapUtils.pointer_to_coord(
                self.drawing_area.get_allocation(),
                pointer, self.drawing_area.center, self.get_zoom())

    ## add mouse location latitude/longitude to clipboard
    def mouse_location(self, pointer=None):
        coord = self.pointer_to_world_coord(pointer)
        clipboard = gtk.Clipboard()
        clipboard.set_text("Latitude=%.6f, Longitude=%.6f" % (coord[0], coord[1]))

    ## add GPS location latitude/longitude to clipboard
    def gps_location(self):
        clipboard = gtk.Clipboard()
        if self.gps and self.gps.gpsfix:
            clipboard.set_text("Latitude=%.6f, Longitude=%.6f" %
                              (self.gps.gpsfix.latitude, self.gps.gpsfix.longitude))
        else:
            clipboard.set_text("No GPS location detected.")

    ## Add a marker
    def add_marker(self, pointer=None):
        coord = self.pointer_to_world_coord(pointer)
        self.marker.append_marker(coord)
        self.refresh()

    ## Show the bottom panel with the export
    def show_export(self, pointer=None):
        size = self.get_size()
        if size[0] < 700:
            self.resize(700, size[1])
        self.visual_dlconfig['active'] = False
        self.visual_dltool.set_active(False)
        self.top_panel.hide()
        self.export_panel.show()
        self.export_pbar.off()
        #Set the zoom level
        zl = self.get_zoom()
        if zl < (self.map_min_zoom + 2):
            zl = self.map_min_zoom + 2
        self.expZoom.set_value(zl - 2)
        self.do_zoom(zl, True, pointer)

    ## Update the Map Export Widgets
    def update_export(self, *args):
        self.visual_dlconfig["show_rectangle"] = False
        if self.export_panel.flags() & gtk.VISIBLE:
            # Convert given size to a tile size factor
            widthFact = int(self.sbWidth.get_value() / TILES_WIDTH)
            self.sbWidth.set_value(widthFact * TILES_WIDTH)
            heightFact = int(self.sbHeight.get_value() / TILES_HEIGHT)
            self.sbHeight.set_value(heightFact * TILES_HEIGHT)
            # Get Upper & Lower points
            coord = mapUtils.tile_to_coord(
                self.drawing_area.center, self.get_zoom()
            )
            tile = mapUtils.coord_to_tile(
                (coord[0], coord[1], self.expZoom.get_value_as_int())
            )
            self.tPoint['xLow'] = tile[0][0] - int(widthFact / 2)
            self.tPoint['xHigh'] = tile[0][0] + (widthFact - int(widthFact / 2))
            self.tPoint['yLow'] = tile[0][1] - int(heightFact / 2)
            self.tPoint['yHigh'] = tile[0][1] + (heightFact - int(heightFact / 2))

            lowCoord = mapUtils.tile_to_coord(
                ((self.tPoint['xLow'], self.tPoint['yLow']),
                 (0, 0)), self.expZoom.get_value_as_int()
            )
            self.entryUpperLeft.set_text(str(lowCoord[0]) + ", " + str(lowCoord[1]))
            self.tPoint['FileName'] = "coord=%.6f,%.6f_zoom=%d.png" % lowCoord

            highCoord = mapUtils.tile_to_coord(
                ((self.tPoint['xHigh'], self.tPoint['yHigh']),
                 (0, 0)), self.expZoom.get_value_as_int()
            )
            self.entryLowerRight.set_text(str(highCoord[0]) + ", " + str(highCoord[1]))

            # Set the vars to draw rectangle
            lowScreen = self.drawing_area.coord_to_screen(
                lowCoord[0], lowCoord[1], self.get_zoom()
            )
            if lowScreen:
                self.visual_dlconfig["x_rect"] = lowScreen[0]
                self.visual_dlconfig["y_rect"] = lowScreen[1]
                highScreen = self.drawing_area.coord_to_screen(
                    highCoord[0], highCoord[1], self.get_zoom()
                )
                if highScreen:
                    self.visual_dlconfig["show_rectangle"] = True
                    self.visual_dlconfig["width_rect"] = \
                        highScreen[0] - lowScreen[0]
                    self.visual_dlconfig["height_rect"] = \
                        highScreen[1] - lowScreen[1]
                else:
                    self.do_zoom(self.get_zoom() + 1, True)
            else:
                self.do_zoom(self.get_zoom() + 1, True)

            self.drawing_area.repaint()

    def export_done(self, text):
        self.export_pbar.off()
        self.export_box.show()
        #error_msg(self, "Export completed \n\n" + text)

    ## Export tiles to one big map
    def do_export(self, button):
        self.export_box.hide()
        self.export_pbar.on()
        self.update_export()
        self.ctx_map.do_export(
            self.tPoint, self.expZoom.get_value_as_int(), self.layer,
            not self.cb_offline.get_active(), self.conf,
            (self.sbWidth.get_value_as_int(), self.sbHeight.get_value_as_int()),
            gui_callback(self.export_done)
        )

    def add_ruler_segment(self, event):
        self.from_coord = self.pointer_to_world_coord((event.x, event.y))
        x = self.from_coord[0]
        y = self.from_coord[1]
        self.ruler_coord.append((x, y))

        l = len(self.ruler_coord)

        if l > 1:
            z = mapUtils.countDistanceFromLatLon(
                    (self.ruler_coord[l - 2][0], self.ruler_coord[l - 2][1]),
                    (self.ruler_coord[l - 1][0], self.ruler_coord[l - 1][1])
                )
            unit = self.conf.units
            if unit != UNIT_TYPE_KM:
                z = mapUtils.convertUnits(UNIT_TYPE_KM, unit, z)
            self.draw_overlay()
            self.total_dist = self.total_dist + z
            self.status_bar.distance(z, DISTANCE_UNITS[unit], self.total_dist)
        else:
            self.status_bar.text("Click to second point to show ruler and distances")

    def remove_last_ruler_segment(self):
        l = len(self.ruler_coord)
        if l > 0:
            z = mapUtils.countDistanceFromLatLon(
                    (self.ruler_coord[l - 2][0], self.ruler_coord[l - 2][1]),
                    (self.ruler_coord[l - 1][0], self.ruler_coord[l - 1][1])
                )
            unit = self.conf.units
            if unit != UNIT_TYPE_KM:
                z = mapUtils.convertUnits(UNIT_TYPE_KM, unit, z)
            self.total_dist = self.total_dist - z
            self.ruler_coord.pop()
            self.drawing_area.repaint()
            new_l = len(self.ruler_coord)
            if new_l > 1:
                self.status_bar.text("Total distance = %.3f km" % (self.total_dist))
            elif new_l == 1:
                self.status_bar.text("Click to second point to show ruler and distances")
            else:
                self.ruler_coord = list()
                self.drawing_area.repaint()
                self.drawing_area.da_set_cursor()
                self.Ruler = not self.Ruler
        else:
            self.Ruler = not self.Ruler
            self.status_bar.push("Ruler Mode switched off")
            self.drawing_area.repaint()

    ## Handles Right & Double clicks events in the drawing_area
    def da_click_events(self, w, event):
        ## Single click event
        # On button press, set the coordinates
        if event.type == gtk.gdk.BUTTON_PRESS:
            self.dragXY = (event.x, event.y)
        elif event.type == gtk.gdk.BUTTON_RELEASE:
            # Right-Click event shows the popUp menu
            if event.button == 3:
                self.myPointer = (event.x, event.y)
                w.popup(None, None, None, event.button, event.time)
            # If window hasn't been dragged, it's possible to add marker or ruler
            # if the window has been dragged, just ignore it...
            if abs(event.x - self.dragXY[0]) < 5 and abs(event.y - self.dragXY[1]) < 5:
                # Ctrl + Click adds a marker
                if (event.state & gtk.gdk.CONTROL_MASK):
                    self.add_marker((event.x, event.y))
                # Left-Click in Ruler Mode
                elif event.button == 1 and self.Ruler:
                    self.add_ruler_segment(event)

        # Double-Click event Zoom In or Out
        elif event.type == gtk.gdk._2BUTTON_PRESS:
            # Alt + 2Click Zoom Out
            if (event.state & gtk.gdk.MOD1_MASK):
                self.do_zoom(self.get_zoom() + 1, True, (event.x, event.y))
            # 2Click Zoom In
            else:
                self.do_zoom(self.get_zoom() - 1, True, (event.x, event.y))

    ## Handles the mouse motion over the drawing_area
    def da_motion(self, w, event):
        if (event.state & gtk.gdk.BUTTON1_MASK):
            self.gps_idle_time = time.time()
            self.drawing_area.da_move(event.x, event.y, self.get_zoom())
            if (event.state & gtk.gdk.SHIFT_MASK):
                self.visual_download()
            self.update_export()

        if self.conf.statusbar_type == STATUS_MOUSE and not self.Ruler:
            coord = self.pointer_to_world_coord((event.x, event.y))
            self.status_bar.coordinates(coord[0], coord[1])

    def view_credits(self, menuitem):
        w = OurCredits()
        w.destroy()

    def visual_dltool_toggled(self, menuitem):
        if not self.visual_dlconfig.get('downloader', False):
            self.visual_dlconfig['downloader'] = MapDownloader(self.ctx_map, self.conf.maxthreads)

        if menuitem.get_active():
            if self.check_bulk_down():
                self.visual_dlconfig['active'] = True
                self.draw_overlay()
            else:
                menuitem.set_active(False)
        else:
            self.visual_dlconfig['active'] = False
            self.drawing_area.repaint()

    def visualdl_cb(self, *args, **kwargs):
        self.visualdl_update(1)

    def visualdl_update(self, recd=0):
        if self.visual_dlconfig.get('downloader', False):
            temp = self.visual_dlconfig.get('recd', 0)
            self.visual_dlconfig['qd'] = \
                    self.visual_dlconfig['downloader'].qsize() + temp + recd
            self.visual_dlconfig['recd'] = temp + recd
        if self.visual_dlconfig.get('recd', 0) >= \
                self.visual_dlconfig.get('qd', 0):
            self.visual_dlconfig['qd'], self.visual_dlconfig['recd'] = 0, 0
        self.drawing_area.repaint()

    def expose_cb(self, drawing_area, event):
        online = not self.cb_offline.get_active() and not self.hide_dlfeedback
        self.hide_dlfeedback = False
        force_update = self.cb_forceupdate.get_active()
        rect = drawing_area.get_allocation()
        zl = self.get_zoom()
        self.downloader.query_region_around_point(
            self.drawing_area.center, (rect.width, rect.height), zl, self.layer,
            gui_callback(self.tile_received),
            online=online, force_update=force_update,
            conf=self.conf,
        )
        self.downloading = self.downloader.qsize()
        self.draw_overlay()

    def scroll_cb(self, widget, event):
        dlbool = self.visual_dlconfig.get("active", False)
        intVal = 1 if (event.direction != gtk.gdk.SCROLL_UP) else -1
        sz, zl = 0, 0
        if dlbool and (event.state & gtk.gdk.CONTROL_MASK):
            zl = intVal
        elif dlbool and (event.state & gtk.gdk.SHIFT_MASK):
            sz = intVal
        else:
            xyPointer = self.drawing_area.get_pointer()
            self.do_zoom(self.get_zoom() + intVal, dPointer=xyPointer)

        self.visual_dlconfig["zl"] = self.visual_dlconfig.get('zl', -2) + zl
        self.visual_dlconfig['sz'] = self.visual_dlconfig.get('sz', 4) - sz
        if self.visual_dlconfig.get('zl', -2) > -1:
            self.visual_dlconfig["zl"] = -1
        if self.visual_dlconfig.get('sz', 4) < 1:
            self.visual_dlconfig['sz'] = 1
        if self.visual_dlconfig.get('zl', -2) + self.get_zoom() < -2:
            self.visual_dlconfig['zl'] = -2 - self.get_zoom()
        if sz != 0 or zl != 0:
            self.drawing_area.repaint()

    def tile_received(self, tile_coord, layer, download=False):
        if download:
            self.downloading = self.downloader.qsize()
            if self.downloading <= 0:
                self.hide_dlfeedback = True
                self.drawing_area.repaint()
        hybridsat = (self.layer == LAYER_HYB and layer == LAYER_SAT)
        if (self.layer == layer or hybridsat) and self.get_zoom() == tile_coord[2]:
            da = self.drawing_area
            rect = da.get_allocation()
            xy = mapUtils.tile_coord_to_screen(tile_coord, rect, self.drawing_area.center)
            if xy:
                # here we keep a list of all foreground tiles that turn up
                # when there is no corresponding background tile yet
                if layer == LAYER_HYB:
                    if tile_coord not in self.background:
                        self.foreground.append(tile_coord)
                    else:
                        # keep the lists as bare as possible
                        self.background.remove(tile_coord)
                # keep the background tile list up to date - add background
                # tile to list unless we're all set to add foreground overlay
                if hybridsat and tile_coord not in self.foreground:
                    self.background.append(tile_coord)

                gc = da.style.black_gc
                force_update = self.cb_forceupdate.get_active()
                img = self.ctx_map.load_pixbuf(tile_coord, layer, force_update)
                if hybridsat:
                    img2 = self.ctx_map.load_pixbuf(tile_coord, LAYER_HYB,
                                                    force_update)
                for x, y in xy:
                    da.window.draw_pixbuf(gc, img, 0, 0, x, y,
                                          TILES_WIDTH, TILES_HEIGHT)
                    # here we [re-]add foreground overlay providing
                    # it is already in memory
                    if hybridsat and tile_coord in self.foreground:
                        self.foreground.remove(tile_coord)
                        da.window.draw_pixbuf(gc, img2, 0, 0, x, y,
                                              TILES_WIDTH, TILES_HEIGHT)

    def draw_overlay(self):
        if self.export_panel.flags() & gtk.VISIBLE:
            self.drawing_area.draw_overlay(
                self.get_zoom(), self.conf, self.crossPixbuf, self.dlpixbuf,
                self.downloading > 0, self.visual_dlconfig
            )
        else:
            self.drawing_area.draw_overlay(
                self.get_zoom(), self.conf, self.crossPixbuf, self.dlpixbuf,
                self.downloading > 0, self.visual_dlconfig, self.marker,
                self.ctx_map.get_locations(), self.entry.get_text(),
                self.showMarkers, self.gps,
                self.ruler_coord,
                self.shown_tracks, self.draw_track_distance
            )

    ## Handles the pressing of F11 & F12
    def full_screen(self, keyval):
        # F11 = 65480
        if keyval == 65480:
            if self.get_decorated():
                self.set_keep_above(True)
                self.set_decorated(False)
                self.fullscreen()
            else:
                self.unfullscreen()
                self.set_decorated(True)
                self.set_keep_above(False)

        # F12 = 65481
        elif keyval == 65481:
            self.export_panel.hide()
            self.export_pbar.off()
            if self.get_border_width() > 0:
                self.left_panel.hide()
                self.top_panel.hide()
                self.set_border_width(0)
            else:
                self.left_panel.show()
                self.top_panel.show()
                self.set_border_width(10)
            self.update_export()
        # ESC = 65307
        elif keyval == 65307:
            self.unfullscreen()
            self.export_panel.hide()
            self.export_pbar.off()
            self.left_panel.show()
            self.top_panel.show()
            self.set_border_width(10)
            self.set_keep_above(False)
            self.set_decorated(True)
            self.update_export()

    ## Handles the keyboard navigation
    def navigation(self, keyval, zoom):
        # Left  = 65361  Up   = 65362
        # Right = 65363  Down = 65364
        if keyval in range(65361, 65365):
            self.drawing_area.da_jump(keyval - 65360, zoom)
            self.gps_idle_time = time.time()

        # Page Up = 65365  Page Down = 65366
        # Home    = 65360  End       = 65367
        elif keyval == 65365:
            self.drawing_area.da_jump(2, zoom, True)
        elif keyval == 65366:
            self.drawing_area.da_jump(4, zoom, True)
        elif keyval == 65360:
            self.drawing_area.da_jump(1, zoom, True)
        elif keyval == 65367:
            self.drawing_area.da_jump(3, zoom, True)

        # Minus = [45,65453]   Zoom Out
        # Plus  = [43,65451]   Zoom In
        elif keyval in [45, 65453]:
            self.do_zoom(zoom + 1, True)
        elif keyval in [43, 65451]:
            self.do_zoom(zoom - 1, True)

        # Space = 32   ReCenter the GPS
        elif keyval == 32:
            self.reCenter_gps = True
        # Handle the numbers
        elif 49 <= keyval <= 57:
            try:
                self.cmb_layer.set_active(keyval - 49)
            except:
                pass

        # M = 77,109  S = 83,115  T = 84,116, H = 72,104
        if not self.conf.oneDirPerMap:
            if keyval in [77, 109]:
                self.cmb_layer.set_active(LAYER_MAP)
            elif keyval in [83, 115]:
                self.cmb_layer.set_active(LAYER_SAT)
            elif keyval in [84, 116]:
                self.cmb_layer.set_active(LAYER_TER)
            elif keyval in [72, 104]:
                self.cmb_layer.set_active(LAYER_HYB)

    ## Handles the Key pressing
    def key_press_event(self, w, event):
        # F11 = 65480, F12 = 65481, ESC = 65307
        if event.keyval in [65480, 65481, 65307]:
            self.full_screen(event.keyval)
        # Q = 113,81 W = 87,119
        if (event.state & gtk.gdk.CONTROL_MASK) != 0 and event.keyval in [113, 81, 87, 119]:
            self.on_delete()
            self.destroy()
        # F1 = 65471  Help
        elif event.keyval == 65470:
            webbrowser_open(WEB_ADDRESS)
        # F2 = 65471
        elif event.keyval == 65471:
            self.show_export()
        # F3 == 65472
        elif event.keyval == 65472:
            self.gps_window_clicked()
        # F4 = 65473
        elif event.keyval == 65473:
            fileName = FileChooser(mapUtils.getHome(), 'Select KML File to import')
            if fileName:
                kmlResponse = kml_to_markers(fileName, self.marker)
                if kmlResponse:
                    error_msg(self, "There was an error importing: \n" +
                        "\n" + str(type(kmlResponse)) +
                        "\n" + str(kmlResponse))
        # F5 = 65474
        elif event.keyval == 65474:
            self.refresh()
        # F6 = 65475
        elif event.keyval == 65475:
            if not(self.export_panel.flags() & gtk.VISIBLE):
                self.visual_dlconfig['active'] = \
                    not self.visual_dlconfig.get('active', False)
                self.visual_dltool.set_active(
                        self.visual_dlconfig.get('active', False))
                if not self.visual_dlconfig.get('downloader', False):
                    self.visual_dlconfig['downloader'] = \
                            MapDownloader(self.ctx_map, self.conf.maxthreads)
                self.drawing_area.repaint()
        # F7 = 65476 for Ruler
        elif event.keyval == 65476:
            if not self.Ruler:
                self.total_dist = 0.00
                self.ruler_coord = list()
                self.drawing_area.da_set_cursor(gtk.gdk.PENCIL)
                self.status_bar.text("Ruler Mode - Click for Starting Point")
                self.Ruler = not self.Ruler
            else:
                rulerOff = False
                if len(self.ruler_coord) > 1:
                    confirm = user_confirm(self, 'Do you want to use ruler as track?')
                    if len(self.ruler_coord) > 1 and confirm == gtk.RESPONSE_YES:
                        track = {'name': 'Ruler %i' % self.rulers, 'coords': self.ruler_coord}
                        self.tracks.append(track)
                        self.shown_tracks.append(track)
                        self.rulers += 1
                        rulerOff = True
                        if self.trackw:
                            self.trackw.update_widgets()
                    elif confirm != gtk.RESPONSE_CANCEL:
                        rulerOff = True
                else:
                    rulerOff = True
                if rulerOff:
                    self.status_bar.text("Ruler Mode switched off")
                    self.ruler_coord = []
                    self.drawing_area.repaint()
                    self.drawing_area.da_set_cursor()
                    self.Ruler = not self.Ruler
        # F8 = 65477
        elif event.keyval == 65477:
            self.track_control_clicked()
        # F9 = 65478
        elif event.keyval == 65478:
            self.showMarkers = not self.showMarkers
            self.drawing_area.repaint()
        # if Ruler is active, delete (65535) removes last element from ruler
        elif event.keyval == 65535 and self.Ruler:
            self.remove_last_ruler_segment()

        # All Navigation Keys when in FullScreen
        elif self.get_border_width() == 0:
            self.navigation(event.keyval, self.get_zoom())

    ## All the refresh operations
    def refresh(self, *args):
        self.map_min_zoom = self.ctx_map.get_min_zoom(self.conf.map_service)
        self.map_max_zoom = self.ctx_map.get_max_zoom(self.conf.map_service)
        self.scale.set_range(self.map_min_zoom, self.map_max_zoom)
        if self.cmb_layer.child.get_text() == '':
            self.cmb_layer.combo_popup()
        self.enable_gps(False)
        self.update_export()
        self.marker.refresh()
        self.update_cmb_gps()
        self.drawing_area.repaint()
        if self.conf.statusbar_type == STATUS_NONE:
            self.status_bar.hide()
        else:
            self.status_bar.show()

    ## Final actions before main_quit
    def on_delete(self, *args):
        self.unfullscreen()
        self.unmaximize()
        sz = self.get_size()
        location = self.get_position()
        self.hide()
        if mapGPS.available and self.gps:
            self.gps.stop_all()
        self.downloader.stop_all()
        if self.visual_dlconfig.get('downloader', False):
            self.visual_dlconfig['downloader'].stop_all()
        self.ctx_map.finish()
        # If there was an update show it
        if self.update:
            self.update.finish()
        gtk.gdk.threads_leave()
        if self.conf.save_at_close:
            self.conf.save_layer = self.layer
            self.conf.save_width = sz[0]
            self.conf.save_height = sz[1]
            self.conf.save_hlocation = location[0]
            self.conf.save_vlocation = location[1]
            self.conf.save()
        return False

    def enable_gps(self, show_warning):
        if self.gps:
            if self.gps.type != self.conf.gps_type \
              or self.gps.serial_port != self.conf.gps_serial_port \
              or self.gps.baudrate != self.conf.gps_serial_baudrate:
                self.gps.stop_all()
                self.gps_valid = True
                self.gps = mapGPS.GPS(
                    self.gps_callback,
                    self.conf
                )
        else:
            self.gps_valid = True
            self.gps = mapGPS.GPS(
                self.gps_callback,
                self.conf
            )
        if show_warning and self.gps and not self.gps_warning():
            self.gps = None

    def gps_warning(self):
        if mapGPS.available and self.conf.map_service in NO_GPS:
            if (self.conf.gps_type > TYPE_OFF):
                return legal_warning(self, self.conf.map_service, "gps integration")
        return True

    def pane_notify(self, pane, gparamspec, intPos):
        if gparamspec.name == 'position':
            panePos = pane.get_property('position')
            if (panePos < intPos - 2):
                pane.set_position(0)
            elif (panePos > intPos + 2):
                pane.set_position(intPos + 2)

    def __init__(self, parent=None, config_path=None):
        self.conf = MapConf(config_path)
        self.crossPixbuf = mapPixbuf.cross()
        self.dlpixbuf = mapPixbuf.downloading()
        self.marker = MyMarkers(self.conf.init_path)
        self.ctx_map = MapServ(self.conf)
        self.map_min_zoom = self.ctx_map.get_min_zoom(self.conf.map_service)
        self.map_max_zoom = self.ctx_map.get_max_zoom(self.conf.map_service)

        self.downloader = MapDownloader(self.ctx_map, self.conf.maxthreads)
        if self.conf.save_at_close and (LAYER_MAP <= self.conf.save_layer <= LAYER_HYB):
            self.layer = self.conf.save_layer
        else:
            self.layer = LAYER_MAP
        self.background = []
        self.foreground = []
        self.save_gps = []
        self.gps = None
        self.enable_gps(True)
        self.downloading = 0
        self.visual_dlconfig = {}
        self.hide_dlfeedback = False
        self.tracks = []
        self.shown_tracks = []
        self.rulers = 1
        self.ruler_coord = []
        self.dragXY = None

        # Initialize windows as None
        self.gpsw = None
        self.trackw = None
        self.settingsw = None

        self.draw_track_distance = False

        gtk.Window.__init__(self)
        try:
            self.set_screen(parent.get_screen())
        except AttributeError:
            self.connect("destroy", lambda *w: gtk.main_quit())

        self.connect('key-press-event', self.key_press_event)
        self.connect('delete-event', self.on_delete)

        self.top_panel = self.__create_top_paned()
        self.left_panel = self.__create_left_paned(self.conf)
        self.export_panel = self.__create_export_paned()
        self.status_bar = StatusBar()

        ico = mapPixbuf.ico()
        if ico:
            self.set_icon(ico)

        hpaned = gtk.HPaned()
        hpaned.connect("notify", self.pane_notify, 30)
        hpaned.pack1(self.left_panel, False, True)
        hpaned.pack2(self.__create_right_paned(), True, True)

        inner_vp = gtk.VPaned()
        inner_vp.pack1(hpaned, True, True)
        inner_vp.pack2(self.export_panel, False, False)

        vpaned = gtk.VPaned()
        vpaned.connect("notify", self.pane_notify, 89)
        vpaned.pack1(self.top_panel, False, True)
        vpaned.pack2(inner_vp)

        vbox = gtk.VBox(False, 0)
        vbox.pack_start(vpaned, True, True, 0)
        vbox.pack_start(self.status_bar, False, False, 0)
        self.add(vbox)

        self.connect('focus-in-event', self.refresh)
        self.set_title(" GMapCatcher ")
        self.set_border_width(10)
        self.set_size_request(450, 450)
        if self.conf.save_at_close:
            self.set_default_size(self.conf.save_width, self.conf.save_height)
        else:
            self.set_default_size(self.conf.init_width, self.conf.init_height)
        self.combo.set_completion(self.ctx_map, self.confirm_clicked, self.conf)
        self.combo.default_entry()
        self.drawing_area.center = self.conf.init_center
        self.show_all()
        if self.conf.save_at_close:
            self.move(self.conf.save_hlocation, self.conf.save_vlocation)
        if self.conf.statusbar_type == STATUS_NONE:
            self.status_bar.hide()
        self.export_panel.hide()
        self.drawing_area.da_set_cursor()
        self.entry.grab_focus()
        if self.conf.auto_refresh > 0:
            gobject.timeout_add(self.conf.auto_refresh, self.refresh)


def main(conf_path):
    MainWindow(config_path=conf_path)
    gtk.main()

if __name__ == "__main__":
    conf_path = None
    for arg in sys.argv:
        arg = arg.lower()
        if arg.startswith('--config-path='):
            conf_path = arg[14:]
            continue

    main(conf_path)
    pid = os.getpid()
    # send ourselves sigquit, particularly necessary in posix as
    # download threads may be holding system resources - python
    # signals in windows implemented in python 2.7
    if os.name == 'posix':
        os.kill(pid, signal.SIGQUIT)
