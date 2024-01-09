import operator
import sys
import functools

import dbus # type: ignore

from gi.repository import GObject, GLib # type: ignore
from dbus.mainloop.glib import DBusGMainLoop # type: ignore

BLUEZ_SERVICE_NAME: str = "org.bluez"
GATT_SERVICE_IFACE: str = "org.bluez.GattService1"
GATT_CHRC_IFACE: str    = "org.bluez.GattCharacteristic1"

DBUS_OM_IFACE: str = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE: str = "org.freedesktop.DBus.Properties"

HR_SVC_UUID: str   = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MSRMT_UUID: str = "00002a37-0000-1000-8000-00805f9b34fb"

def val2hb(value):
	flags = value[0]
	value_fmt = flags & 0x01
	match value_fmt:
		case 0x00:
			return value[1]
		case _:
			return value[1] | (value[2] << 8)
	pass

def hr_msrmt_changed_cb(iface, changed_props, invalidated_props):
	if iface != GATT_CHRC_IFACE:
		return

	if not len(changed_props):
		return

	value = changed_props.get("Value", None)
	if not value:
		return

	hr_msrmt = val2hb(value)

	print("value: " + str(int(hr_msrmt)))

	pass

def chrc_map(bus, chrc_path):
	chrc = bus.get_object(BLUEZ_SERVICE_NAME, chrc_path)
	chrc_props = chrc.GetAll(GATT_CHRC_IFACE, dbus_interface=DBUS_PROP_IFACE)
	uuid = chrc_props["UUID"]
	return (chrc, chrc_props, uuid)

def item2svc(bus, chrcs, item):
	path = item[0]
	svc = bus.get_object(BLUEZ_SERVICE_NAME, path)
	svc_props = svc.GetAll(GATT_SERVICE_IFACE, dbus_interface=DBUS_PROP_IFACE)
	uuid = svc_props["UUID"]
	hr_svc_cand = (svc, svc_props, path, uuid)

	c_paths = filter(lambda d: d.startswith(path + "/"), chrcs)
	mapd = map(lambda chrc_path: chrc_map(bus, chrc_path), c_paths)
	filtered = filter(lambda t: HR_MSRMT_UUID == t[2], mapd)
	hr_msrmt_chrc = next(filtered, None)
	return (hr_svc_cand, hr_msrmt_chrc)

def is_noreply_error(error):
	estr: str = str(error)
	return estr.startswith("org.freedesktop.DBus.Error.NoReply")

def generic_error_cb_new(mainloop):
	def cb(error):
		if is_noreply_error(error):
			print("No reply got.")
			return
		print("D-Bus call failed: " + str(error))
		print(error)
		mainloop.quit()
		pass
	return cb

def ifaces_removed_cb_new(hr_svc, mainloop):
	def cb(obj_path, _ifaces):
		if not hr_svc:
			return
		if obj_path == hr_svc[2]:
			print("Service was removed")
			mainloop.quit()
		pass
	return cb

def get_svc(bus, hr_svc, mainlp):
	interfaces_removed_cb = ifaces_removed_cb_new(hr_svc, mainlp)
	om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
	om.connect_to_signal("InterfacesRemoved", interfaces_removed_cb)

	objects = om.GetManagedObjects()

	items = objects.items()
	filtered = filter(lambda tup: GATT_CHRC_IFACE in tup[1].keys(), items)
	chrcs = map(operator.itemgetter(0), filtered)

	filtered = filter(lambda tup: GATT_SERVICE_IFACE in tup[1].keys(), items)
	mapd = map(functools.partial(item2svc, bus, chrcs), filtered)
	svc_tup = next(filter(lambda t: HR_SVC_UUID == t[0][3], mapd), None)
	if not(svc_tup):
		print("No heart rate service found")
		sys.exit(1)
	return svc_tup

def start_client(generic_error_cb, hr_msrmt_chrc):
	hr_msrmt_prop_iface = dbus.Interface(hr_msrmt_chrc[0], DBUS_PROP_IFACE)
	hr_msrmt_prop_iface.connect_to_signal("PropertiesChanged", hr_msrmt_changed_cb)
	hr_msrmt_chrc[0].StartNotify(
		reply_handler = lambda: print("heart meas noti. enabled"),
		error_handler=generic_error_cb,
		dbus_interface=GATT_CHRC_IFACE,
	)


def main():
	DBusGMainLoop(set_as_default=True)
	bus = dbus.SystemBus()
	mainloop = GLib.MainLoop()

	hr_service = None
	svc_tup = get_svc(bus, hr_service, mainloop)
	hr_service = svc_tup[0]
	hr_msrmt_chrc = svc_tup[1]

	generic_error_cb = generic_error_cb_new(mainloop)
	start_client(generic_error_cb, hr_msrmt_chrc)

	mainloop.run()

	pass

main()
