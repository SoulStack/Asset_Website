#!/usr/bin/python -u
# coding=utf-8
# "DATASHEET": http://cl.ly/ekot
# https://gist.github.com/kadamski/92653913a53baf9dd1a8
from __future__ import print_function
import serial, struct, sys, time, json, subprocess
import os
import asyncio
from azure.iot.device import X509
from azure.iot.device.aio import ProvisioningDeviceClient
from azure.iot.device.aio import IoTHubDeviceClient
from azure.iot.device import Message
import uuid

DEBUG = 0
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1
PERIOD_CONTINUOUS = 0

JSON_FILE = './html/aqi.json'

MQTT_HOST = ''
MQTT_TOPIC = '/weather/particulatematter'

ser = serial.Serial()
ser.port = "/dev/ttyUSB0"

ser.baudrate = 9600

ser.open()
ser.flushInput()

byte, data = 0, ""

provisioning_host = os.getenv("PROVISIONING_HOST")
id_scope = os.getenv("PROVISIONING_IDSCOPE")
registration_id = os.getenv("DPS_X509_REGISTRATION_ID")

def dump(d, prefix=''):
	print(prefix + ' '.join(x.encode('hex') for x in d))
def construct_command(cmd, data=[]):
	assert len(data) <= 12
	data += [0,]*(12-len(data))
	checksum = (sum(data)+cmd-2)%256
	ret = "\xaa\xb4" + chr(cmd)
	ret += ''.join(chr(x) for x in data)
	ret += "\xff\xff" + chr(checksum) + "\xab"
	if DEBUG:
		dump(ret,'> ')
	return ret.encode()
def process_data(d):
	r = struct.unpack('<HHxxBB', d[2:])
	pm25 = r[0]/10.0
	pm10 = r[1]/10.0
	checksum = sum(v for v in d[2:8])%256
	return [pm25, pm10]
def process_version(d):
	r = struct.unpack('<BBBHBB', d[3:])
	checksum = sum(v for v in d[2:8])%256
	print("Y: {}, M: {}, D: {}, ID: {}, CRC={}".format(r[0], r[1], r[2], hex(r[3]), "OK" if (checksum==r[4] and r[5]==0xab) else "NOK"))
def read_response():
	byte=0
	while byte != b'\xaa':
		byte = ser.read(size=1)
	d=ser.read(size=9)
	if DEBUG:
		dump(d,'< ')
	return byte+d
def cmd_set_mode(mode=MODE_QUERY):
	ser.write(construct_command(CMD_MODE, [0x1, mode]))
	read_response()
def cmd_query_data():
	ser.write(construct_command(CMD_QUERY_DATA))
	d = read_response()
	values = []
	if d[1] == ord(b'\xc0'):
		values = process_data(d)
	return values
def cmd_set_sleep(sleep):
	mode = 0 if sleep else 1
	ser.write(construct_command(CMD_SLEEP, [0x1, mode]))
	read_response()
def cmd_set_working_period(period):
	ser.write(construct_command(CMD_WORKING_PERIOD, [0x1, period]))
	read_response()
def cmd_firmware_ver():
	ser.write(construct_command(CMD_FIRMWARE))
	d = read_response()
	process_version(d)
def cmd_set_id(id):
	id_h = (id>>8) % 256
	id_l = id % 256
	ser.write(construct_command(CMD_DEVICE_ID, [0]*10+[id_l, id_h]))
	read_response()
async def main():
	x509 = X509(
		cert_file=os.getenv("X509_CERT_FILE"),
		key_file=os.getenv("X509_KEY_FILE"),
		pass_phrase=os.getenv("PASS_PHRASE"),
		)
	provisioning_device_client = ProvisioningDeviceClient.create_from_x509_certificate(
		provisioning_host=provisioning_host,
		registration_id=registration_id,
		id_scope=id_scope,
		x509=x509,
		)
	registration_result = await provisioning_device_client.register()
	print("The complete registration result is")
	print(registration_result.registration_state)
	if registration_result.status =="assigned":
		print("Device is starting to send data to azure cloud")
		device_client = IoTHubDeviceClient.create_from_x509_certificate(
			x509=x509,
			hostname=registration_result.registration_state.assigned_hub,
			device_id=registration_result.registration_state.device_id,
			)
		await device_client.connect()
		print("Sending pm datas to azure iot hub")
		while True:
			try:
				cmd_set_sleep(0)
				values = cmd_query_data()
				if values is not None and len(values)==2:
					await device_client.send_message("PM25"+str(values[0]))
					print("sending second reading")
					await device_client.send_message("PM10"+str(values[1]))
					time.sleep(5)
			except Exception as e:
				raise
			else:
				fake_data= "fake"
				await device_client.send_message(str(fake_data))
			finally:
				await device_client.disconnect()
	else:
		print("Couldn't able to connect azure, please check")
if __name__ == '__main__':
	asyncio.run(main())
	cmd_set_sleep(0)
	cmd_firmware_ver()
	cmd_set_working_period(PERIOD_CONTINUOUS)
	cmd_set_mode(MODE_QUERY)
