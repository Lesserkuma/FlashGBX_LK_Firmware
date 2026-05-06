# -*- coding: utf-8 -*-
# LK Firmware Usage Example
# Author: Lesserkuma (github.com/Lesserkuma)

import struct, time, serial, serial.tools.list_ports

class LK_Device:
	DEVICE = None
	DEVICE_IS_JOEYJR = False
	FIRMWARE_INFO = None
	MODE = None

	def __init__(self, port=None, baudrate=1000000):
		if self.DEVICE is not None and self.DEVICE.isOpen(): self.DEVICE.close()

		is_joeyjr = False
		if port is None:
			comports = serial.tools.list_ports.comports()
			for i in range(0, len(comports)):
				if comports[i].vid == 0x483 and comports[i].pid == 0x5740: # Joey Jr VID/PID
					port = comports[i].device
					self.DEVICE_IS_JOEYJR = True
					break
				elif comports[i].vid == 0x1A86 and comports[i].pid == 0x7523: # GBxCart RW and GBFlash VID/PID
					port = comports[i].device
					break
				elif comports[i].vid == 0x1209 and comports[i].pid == 0xB010: # Game Bub VID/PID
					port = comports[i].device
					break

		if port is None:
			raise Exception("No device running LK firmware was found.")

		self.DEVICE = serial.Serial(port, baudrate, timeout=1)
		self.DEVICE.reset_input_buffer()
		self.DEVICE.reset_output_buffer()

	def Close(self):
		if self.DEVICE is not None and self.DEVICE.isOpen():
			self.DEVICE.close()
			self.DEVICE = None

	def WriteFirmwareCommand(self, command, wait_ack=False):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		self.DEVICE.write(struct.pack("B", command))
		if wait_ack:
			if self.DEVICE.read(1) != b'\x01': # LK_STATUS_OK
				return False
		else:
			time.sleep(0.01)
		return True

	def SetFirmwareVariable(self, size, key, value):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		self.WriteFirmwareCommand(0xA6) # LK_CMD_SET_VARIABLE
		self.DEVICE.write(struct.pack("B", size)) # Variable size in bytes
		self.DEVICE.write(struct.pack(">I", key)) # Variable key
		self.DEVICE.write(struct.pack(">I", value)) # Variable value
		if self.DEVICE.read(1) != b'\x01': return False # LK_STATUS_OK
		return True

	def QueryFirmwareVersion(self):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False

		if self.DEVICE_IS_JOEYJR:
			# Joey Jr needs additional commands to enable LK firmware mode
			self.DEVICE.write(b'\x55\xAA')
			time.sleep(0.01)
			device_id = self.DEVICE.read(self.DEVICE.in_waiting)
			if b'Joey Jr' in device_id and b'FW L' not in device_id:
				self.DEVICE.close()
				raise Exception(f"The connected device on port {self.DEVICE.port} is running incompatible firmware.")
			self.DEVICE.write(b'LK')
			if self.DEVICE.read(1) != b'\xFF':
				raise Exception(f"The connected Joey Jr on port {self.DEVICE.port} failed to enter LK firmware mode.")

		self.WriteFirmwareCommand(0xA1) # LK_CMD_QUERY_FW_INFO
		if self.DEVICE.in_waiting == 0:
			raise Exception("The connected device or its installed firmware is not supported.")
		size = struct.unpack("B", self.DEVICE.read(1))[0]
		data = self.DEVICE.read(size)
		data = data[:8]
		keys = ["firmware_signature", "firmware_version", "pcb_version", "firmware_build_timestamp"]
		values = struct.unpack(">cHBI", bytearray(data))
		data = dict(zip(keys, values))
		if data["firmware_version"] < 12:
			raise Exception(f"The old firmware version L{data['firmware_version']} is not supported.")
		size = struct.unpack("B", self.DEVICE.read(1))[0]
		data["device_name"] = self.DEVICE.read(size)[:-1]
		data["power_control_support"] = True if self.DEVICE.read(1) == b'\x01' else False
		data["bootloader_reset_support"] = True if self.DEVICE.read(1) == b'\x01' else False
		self.FIRMWARE_INFO = data
		
		print(f"Found a {data['device_name'].decode("ascii", "replace")} device running LK firmware version L{data['firmware_version']} (build timestamp: {data['firmware_build_timestamp']})")
		return data

	def SetMode(self, mode):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		if mode == "AGB":
			self.WriteFirmwareCommand(0xA2, wait_ack=True) # LK_CMD_SET_MODE_AGB
			self.WriteFirmwareCommand(0xA4, wait_ack=True) # LK_CMD_SET_VOLTAGE_3_3V
		elif mode == "DMG":
			self.WriteFirmwareCommand(0xA3, wait_ack=True) # LK_CMD_SET_MODE_DMG
			self.WriteFirmwareCommand(0xA5, wait_ack=True) # LK_CMD_SET_VOLTAGE_5V
		else:
			return False
		self.MODE = mode
		return True

	def SetCartridgePower(self, on):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		if on:
			self.WriteFirmwareCommand(0xF2, wait_ack=True) # LK_CMD_CART_PWR_ON
			if self.MODE == "AGB":
				self.WriteFirmwareCommand(0xC9, wait_ack=True) # LK_CMD_AGB_BOOTUP_SEQUENCE
		else:
			self.WriteFirmwareCommand(0xF3, wait_ack=True) # LK_CMD_CART_PWR_OFF
		return True

	def CartRead_ROM(self, address, size):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		self.SetFirmwareVariable(1, 0x01, 1) # LK_MODE_ROM_READ
		if self.MODE == "AGB":
			address >>= 1 # AGB mode uses 16-bit addressing, so divide by 2

		self.SetFirmwareVariable(4, 0x00, address) # LK_VAR32_ADDRESS
		self.SetFirmwareVariable(2, 0x00, size) # LK_VAR16_TRANSFER_SIZE
		if self.MODE == "AGB":
			self.WriteFirmwareCommand(0xC1) # LK_CMD_AGB_CART_READ
		elif self.MODE == "DMG":
			self.WriteFirmwareCommand(0xB1) # LK_CMD_DMG_CART_READ
		else:
			return False
		data = self.DEVICE.read(size)
		return data

	def CartWrite_ROM(self, address, value):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False
		self.SetFirmwareVariable(1, 0x01, 2) # LK_MODE_ROM_WRITE
		if self.MODE == "AGB":
			address >>= 1 # AGB mode uses 16-bit addressing, so divide by 2

		if self.MODE == "AGB":
			self.WriteFirmwareCommand(0xC2) # LK_CMD_AGB_CART_WRITE
			self.DEVICE.write(struct.pack(">I", address))
			self.DEVICE.write(struct.pack(">H", value))
		elif self.MODE == "DMG":
			self.WriteFirmwareCommand(0xB2) # LK_CMD_DMG_CART_WRITE
			self.DEVICE.write(struct.pack(">I", address))
			self.DEVICE.write(struct.pack("B", value))
		else:
			return False
		if self.DEVICE.read(1) != b'\x01': return False # LK_STATUS_OK
		return True

	def CartRead_SRAM(self, address, size):
		if self.DEVICE is None or not self.DEVICE.isOpen(): return False

		self.SetFirmwareVariable(1, 0x01, 3) # LK_MODE_RAM_READ
		self.SetFirmwareVariable(2, 0x00, size) # LK_VAR16_TRANSFER_SIZE
		if self.MODE == "AGB":
			self.SetFirmwareVariable(4, 0x00, address) # LK_VAR32_ADDRESS
			self.WriteFirmwareCommand(0xC3) # LK_CMD_AGB_CART_READ_SRAM
		elif self.MODE == "DMG":
			self.SetFirmwareVariable(4, 0x00, 0xA000 + address) # LK_VAR32_ADDRESS
			self.SetFirmwareVariable(1, 0x08, 1) # LK_VAR8_DMG_READ_CS_PULSE
			self.WriteFirmwareCommand(0xB1) # LK_CMD_DMG_CART_READ
		else:
			return False
		data = self.DEVICE.read(size)
		return data


#####

# Examples
def Example_ReadAGB():
	lk_device = LK_Device()
	lk_device.QueryFirmwareVersion()
	lk_device.SetMode("AGB")
	lk_device.SetCartridgePower(True)
	rom_title = lk_device.CartRead_ROM(address=0xA0, size=0xC)
	print("ROM Title:", rom_title.decode("ascii", "ignore"))
	savedata = lk_device.CartRead_SRAM(address=0, size=0x8000)
	with open("sram.sav", "wb") as f: f.write(savedata)
	print("SRAM Data:", len(savedata), "bytes saved to sram.sav")
	lk_device.SetCartridgePower(False)
	lk_device.Close()

def Example_ReadDMG():
	lk_device = LK_Device()
	lk_device.QueryFirmwareVersion()
	lk_device.SetMode("DMG")
	lk_device.SetCartridgePower(True)
	rom_title = lk_device.CartRead_ROM(address=0x134, size=0x10)
	print("ROM Title:", rom_title.decode("ascii", "ignore"))
	# Enable SRAM access
	lk_device.CartWrite_ROM(address=0x6000, value=0x01)
	lk_device.CartWrite_ROM(address=0x0, value=0x0A)
	# Loop over 16 SRAM banks (16 × 8 KiB = 128 KiB SRAM) and concatenate the data
	savedata = bytearray()
	for i in range(0, 16):
		# Set SRAM bank
		lk_device.CartWrite_ROM(address=0x4000, value=i)
		# Read 8 KiB of SRAM
		savedata += lk_device.CartRead_SRAM(address=0, size=0x2000)
	with open("sram.sav", "wb") as f: f.write(savedata)
	print("SRAM Data:", len(savedata), "bytes saved to sram.sav")
	# Disable SRAM access
	lk_device.CartWrite_ROM(address=0x0000, value=0x00)
	lk_device.CartWrite_ROM(address=0x6000, value=0x00)
	lk_device.SetCartridgePower(False)
	lk_device.Close()

if __name__ == "__main__":
	'''These examples read the ROM Title and save SRAM data to a file'''
	Example_ReadAGB() # Game Boy Advance (3.3 volts)
	#Example_ReadDMG() # Game Boy and Game Boy Color (5 volts)
