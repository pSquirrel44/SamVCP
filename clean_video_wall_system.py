#!/usr/bin/env python3
"""
Samsung LH55BECHLGFXGO Video Wall Control System
Complete solution for managing Samsung Business Displays
"""

import asyncio
import socket
import struct
import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import requests
import schedule
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_wall.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'samsung-lh55bechlgfxgo-control-system'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Samsung LH55BECHLGFXGO Specifications and Capabilities
@dataclass
class LH55BECHLGFXGOSpecs:
    """Samsung LH55BECHLGFXGO Display Specifications"""
    model: str = "LH55BECHLGFXGO"
    series: str = "BEC Series"
    screen_size: float = 55.0  # inches
    resolution: str = "1920x1080"
    aspect_ratio: str = "16:9"
    brightness: int = 700  # cd/m²
    contrast_ratio: str = "4000:1"
    viewing_angle: str = "178°/178°"
    response_time: str = "8ms"
    
    # Connectivity
    supported_inputs: List[str] = None
    network_capable: bool = True
    usb_playback: bool = True
    wifi_capable: bool = False
    
    # Video Wall Features
    video_wall_support: bool = True
    max_video_wall_grid: str = "10x10"
    bezel_width: float = 1.7  # mm
    
    # Operating conditions
    operating_temp_range: str = "0°C ~ 40°C"
    storage_temp_range: str = "-20°C ~ 60°C"
    humidity_range: str = "10% ~ 80%"
    
    # Power specifications
    power_consumption_max: int = 130  # watts
    power_consumption_typical: int = 95  # watts
    power_consumption_standby: int = 1  # watts
    
    def __post_init__(self):
        if self.supported_inputs is None:
            self.supported_inputs = [
                "HDMI1", "HDMI2", "DVI-D", "Display Port", 
                "RGB", "Component", "Composite", "USB"
            ]

class MDCCommand(Enum):
    """Samsung MDC Protocol Commands for LH55BECHLGFXGO"""
    # Power Control
    POWER = 0x11
    POWER_STATUS = 0xF1
    
    # Audio Control
    VOLUME = 0x12
    MUTE = 0x13
    SOUND_MODE = 0x16
    
    # Video Control
    INPUT_SOURCE = 0x14
    PICTURE_MODE = 0x15
    PICTURE_SIZE = 0x18
    CONTRAST = 0x22
    BRIGHTNESS = 0x23
    SHARPNESS = 0x24
    COLOR = 0x25
    
    # System Control
    SAFETY_LOCK = 0x17
    PANEL_LOCK = 0x21
    AUTO_ADJUSTMENT = 0x19
    RESET = 0x2A
    
    # Information
    SERIAL_NUMBER = 0x2C
    SOFTWARE_VERSION = 0x2D
    MODEL_NUMBER = 0x2E
    CURRENT_TEMP = 0x2B
    
    # Video Wall
    VIDEO_WALL_MODE = 0x84
    VIDEO_WALL_ON = 0x89
    
    # Time/Schedule
    CLOCK_SET = 0x30
    TIMER_1 = 0x36
    TIMER_2 = 0x37
    TIMER_3 = 0x38
    
    # Network
    NETWORK_CONFIG = 0x3A
    
    # Advanced Features
    LOGO_DISPLAY = 0x1C
    POWER_ON_DELAY = 0x1D
    POWER_OFF_DELAY = 0x1E
    OSD_DISPLAY = 0x3B

class InputSource(Enum):
    """Input sources for Samsung LH55BECHLGFXGO"""
    HDMI1 = 0x21
    HDMI2 = 0x23
    DVI = 0x18
    DISPLAY_PORT = 0x25
    RGB = 0x14
    COMPONENT = 0x08
    COMPOSITE = 0x0C
    USB = 0x60

class PowerState(Enum):
    """Power states"""
    OFF = 0x00
    ON = 0x01

class PictureMode(Enum):
    """Picture modes"""
    STANDARD = 0x00
    MOVIE = 0x01
    DYNAMIC = 0x02
    NATURAL = 0x03
    CALIBRATED = 0x04

@dataclass
class DisplayStatus:
    """Current status of a display"""
    id: int
    name: str
    ip: str
    model: str = "LH55BECHLGFXGO"
    
    # Connection status
    online: bool = False
    responsive: bool = False
    last_seen: Optional[datetime] = None
    error_count: int = 0
    
    # Current settings
    power: bool = False
    volume: int = 50
    muted: bool = False
    input_source: str = "HDMI1"
    picture_mode: str = "STANDARD"
    brightness: int = 50
    contrast: int = 50
    
    # System info
    temperature: Optional[int] = None
    serial_number: Optional[str] = None
    software_version: Optional[str] = None
    uptime: Optional[str] = None
    
    # Content info
    current_content: Optional[str] = None
    content_type: Optional[str] = None
    
    # Video wall info
    video_wall_enabled: bool = False
    grid_position: Optional[Tuple[int, int]] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if self.last_seen:
            data['last_seen'] = self.last_seen.isoformat()
        return data

class SamsungLH55BECHLGFXGOController:
    """Controller for Samsung LH55BECHLGFXGO Business Display"""
    
    def __init__(self, display_id: int, ip: str, port: int = 1515):
        self.display_id = display_id
        self.ip = ip
        self.port = port
        self.specs = LH55BECHLGFXGOSpecs()
        self.status = DisplayStatus(
            id=display_id,
            name=f"Samsung LH55BECHLGFXGO-{display_id}",
            ip=ip
        )
        self.connection_timeout = 10.0
        self.command_timeout = 5.0
        self.max_retries = 3
        
        # Connection management
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        
    async def connect(self) -> bool:
        """Establish connection to display"""
        try:
            logger.info(f"Connecting to Samsung LH55BECHLGFXGO at {self.ip}:{self.port}")
            
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=self.connection_timeout
            )
            
            self.connected = True
            self.status.online = True
            self.status.last_seen = datetime.now()
            self.status.error_count = 0
            
            logger.info(f"Successfully connected to display {self.display_id}")
            return True
            
        except asyncio.TimeoutError:
            logger.warning(f"Connection timeout for display {self.display_id}")
            self.status.online = False
            return False
        except Exception as e:
            logger.error(f"Connection failed for display {self.display_id}: {e}")
            self.status.online = False
            self.status.error_count += 1
            return False
    
    async def disconnect(self):
        """Close connection to display"""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
        
        self.connected = False
        self.reader = None
        self.writer = None
    
    def _create_mdc_packet(self, command: MDCCommand, data: bytes = b'') -> bytes:
        """Create MDC protocol packet for Samsung LH55BECHLGFXGO"""
        header = 0xAA
        cmd = command.value
        display_id = self.display_id
        data_length = len(data)
        
        # Calculate checksum (sum all bytes except checksum itself)
        checksum = (header + cmd + display_id + data_length + sum(data)) & 0xFF
        
        # Build packet
        packet = struct.pack('BBBB', header, cmd, display_id, data_length)
        packet += data
        packet += struct.pack('B', checksum)
        
        return packet
    
    def _parse_mdc_response(self, response: bytes) -> Dict[str, Any]:
        """Parse MDC protocol response"""
        if len(response) < 4:
            return {'success': False, 'error': 'Response too short'}
        
        try:
            header, cmd, display_id, data_length = struct.unpack('BBBB', response[:4])
            
            # Validate response
            if header != 0xAA:
                return {'success': False, 'error': 'Invalid header'}
            
            if display_id != self.display_id:
                return {'success': False, 'error': 'Display ID mismatch'}
            
            # Extract data and checksum
            data = response[4:4+data_length] if data_length > 0 else b''
            
            if len(response) > 4 + data_length:
                checksum = response[4+data_length]
                expected_checksum = (header + cmd + display_id + data_length + sum(data)) & 0xFF
                
                if checksum != expected_checksum:
                    logger.warning(f"Checksum mismatch: expected {expected_checksum}, got {checksum}")
            
            return {
                'success': True,
                'command': cmd,
                'data': data,
                'display_id': display_id,
                'raw_response': response
            }
            
        except struct.error as e:
            return {'success': False, 'error': f'Parse error: {str(e)}'}
    
    async def send_command(self, command: MDCCommand, data: bytes = b'', 
                          expect_response: bool = True) -> Dict[str, Any]:
        """Send command to Samsung LH55BECHLGFXGO display"""
        
        for attempt in range(self.max_retries):
            try:
                # Ensure connection
                if not self.connected:
                    if not await self.connect():
                        continue
                
                # Create and send packet
                packet = self._create_mdc_packet(command, data)
                
                logger.debug(f"Sending command {command.name} to display {self.display_id}")
                self.writer.write(packet)
                await self.writer.drain()
                
                if expect_response:
                    # Wait for response
                    try:
                        response = await asyncio.wait_for(
                            self.reader.read(1024),
                            timeout=self.command_timeout
                        )
                        
                        if response:
                            result = self._parse_mdc_response(response)
                            if result['success']:
                                self.status.responsive = True
                                self.status.last_seen = datetime.now()
                                return result
                            else:
                                logger.warning(f"Command {command.name} failed: {result['error']}")
                                
                    except asyncio.TimeoutError:
                        logger.warning(f"Command {command.name} timeout for display {self.display_id}")
                        self.connected = False
                        continue
                else:
                    # Command sent successfully without expecting response
                    self.status.last_seen = datetime.now()
                    return {'success': True, 'message': f'Command {command.name} sent'}
                
            except Exception as e:
                logger.error(f"Command {command.name} attempt {attempt + 1} failed: {e}")
                self.connected = False
                self.status.error_count += 1
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)  # Wait before retry
        
        # All attempts failed
        self.status.responsive = False
        return {'success': False, 'error': f'Command {command.name} failed after {self.max_retries} attempts'}
    
    # Power Control Methods
    async def power_on(self) -> Dict[str, Any]:
        """Turn display power on"""
        result = await self.send_command(MDCCommand.POWER, bytes([PowerState.ON.value]))
        if result['success']:
            self.status.power = True
        return result
    
    async def power_off(self) -> Dict[str, Any]:
        """Turn display power off"""
        result = await self.send_command(MDCCommand.POWER, bytes([PowerState.OFF.value]))
        if result['success']:
            self.status.power = False
        return result
    
    async def get_power_status(self) -> Dict[str, Any]:
        """Get current power status"""
        result = await self.send_command(MDCCommand.POWER_STATUS)
        if result['success'] and result.get('data'):
            power_state = result['data'][0] if len(result['data']) > 0 else 0
            self.status.power = power_state == PowerState.ON.value
            result['power_on'] = self.status.power
        return result
    
    # Audio Control Methods
    async def set_volume(self, volume: int) -> Dict[str, Any]:
        """Set display volume (0-100)"""
        if not 0 <= volume <= 100:
            return {'success': False, 'error': 'Volume must be between 0-100'}
        
        result = await self.send_command(MDCCommand.VOLUME, bytes([volume]))
        if result['success']:
            self.status.volume = volume
        return result
    
    async def set_mute(self, muted: bool) -> Dict[str, Any]:
        """Set mute state"""
        mute_value = 0x01 if muted else 0x00
        result = await self.send_command(MDCCommand.MUTE, bytes([mute_value]))
        if result['success']:
            self.status.muted = muted
        return result
    
    # Video Control Methods
    async def set_input_source(self, source: InputSource) -> Dict[str, Any]:
        """Set input source"""
        result = await self.send_command(MDCCommand.INPUT_SOURCE, bytes([source.value]))
        if result['success']:
            self.status.input_source = source.name
        return result
    
    async def set_picture_mode(self, mode: PictureMode) -> Dict[str, Any]:
        """Set picture mode"""
        result = await self.send_command(MDCCommand.PICTURE_MODE, bytes([mode.value]))
        if result['success']:
            self.status.picture_mode = mode.name
        return result
    
    async def set_brightness(self, brightness: int) -> Dict[str, Any]:
        """Set brightness (0-100)"""
        if not 0 <= brightness <= 100:
            return {'success': False, 'error': 'Brightness must be between 0-100'}
        
        result = await self.send_command(MDCCommand.BRIGHTNESS, bytes([brightness]))
        if result['success']:
            self.status.brightness = brightness
        return result
    
    async def set_contrast(self, contrast: int) -> Dict[str, Any]:
        """Set contrast (0-100)"""
        if not 0 <= contrast <= 100:
            return {'success': False, 'error': 'Contrast must be between 0-100'}
        
        result = await self.send_command(MDCCommand.CONTRAST, bytes([contrast]))
        if result['success']:
            self.status.contrast = contrast
        return result
    
    # Information Methods
    async def get_temperature(self) -> Dict[str, Any]:
        """Get current display temperature"""
        result = await self.send_command(MDCCommand.CURRENT_TEMP)
        if result['success'] and result.get('data') and len(result['data']) >= 1:
            temp = result['data'][0]
            self.status.temperature = temp
            result['temperature'] = temp
        return result
    
    async def get_serial_number(self) -> Dict[str, Any]:
        """Get display serial number"""
        result = await self.send_command(MDCCommand.SERIAL_NUMBER)
        if result['success'] and result.get('data'):
            serial = result['data'].decode('ascii', errors='ignore').strip()
            self.status.serial_number = serial
            result['serial_number'] = serial
        return result
    
    async def get_model_number(self) -> Dict[str, Any]:
        """Get display model number"""
        result = await self.send_command(MDCCommand.MODEL_NUMBER)
        if result['success'] and result.get('data'):
            model = result['data'].decode('ascii', errors='ignore').strip()
            result['model_number'] = model
        return result
    
    async def get_software_version(self) -> Dict[str, Any]:
        """Get display software version"""
        result = await self.send_command(MDCCommand.SOFTWARE_VERSION)
        if result['success'] and result.get('data'):
            version = result['data'].decode('ascii', errors='ignore').strip()
            self.status.software_version = version
            result['software_version'] = version
        return result
    
    # Video Wall Methods
    async def set_video_wall_mode(self, enabled: bool, h_monitors: int = 1, 
                                 v_monitors: int = 1, h_position: int = 1, 
                                 v_position: int = 1) -> Dict[str, Any]:
        """Configure video wall mode for Samsung LH55BECHLGFXGO"""
        
        # Validate parameters
        if not 1 <= h_monitors <= 10 or not 1 <= v_monitors <= 10:
            return {'success': False, 'error': 'Monitor count must be 1-10 (Samsung LH55BECHLGFXGO supports up to 10x10)'}
        
        if not 1 <= h_position <= h_monitors or not 1 <= v_position <= v_monitors:
            return {'success': False, 'error': 'Position must be within monitor grid'}
        
        # Samsung LH55BECHLGFXGO video wall configuration
        wall_mode = 0x01 if enabled else 0x00
        data = struct.pack('BBBBB', wall_mode, h_monitors, v_monitors, h_position, v_position)
        
        result = await self.send_command(MDCCommand.VIDEO_WALL_MODE, data)
        
        if result['success']:
            self.status.video_wall_enabled = enabled
            if enabled:
                self.status.grid_position = (h_position, v_position)
            else:
                self.status.grid_position = None
        
        return result
    
    # Comprehensive Health Check
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check for Samsung LH55BECHLGFXGO"""
        
        health_data = {
            'display_id': self.display_id,
            'model': 'LH55BECHLGFXGO',
            'ip': self.ip,
            'timestamp': datetime.now().isoformat(),
            'connection': {'status': 'unknown'},
            'power': {'status': 'unknown'},
            'temperature': {'status': 'unknown'},
            'system_info': {},
            'overall_health': 'unknown'
        }
        
        issues = []
        
        try:
            # Test connection
            if not self.connected:
                connection_success = await self.connect()
            else:
                connection_success = True
            
            health_data['connection'] = {
                'status': 'connected' if connection_success else 'failed',
                'error_count': self.status.error_count,
                'last_seen': self.status.last_seen.isoformat() if self.status.last_seen else None
            }
            
            if not connection_success:
                issues.append('Connection failed')
                health_data['overall_health'] = 'critical'
                return health_data
            
            # Test power status
            try:
                power_result = await self.get_power_status()
                health_data['power'] = {
                    'status': 'on' if power_result.get('power_on') else 'off',
                    'responsive': power_result['success']
                }
                
                if not power_result['success']:
                    issues.append('Power status check failed')
                    
            except Exception as e:
                health_data['power'] = {'status': 'error', 'error': str(e)}
                issues.append('Power control error')
            
            # Test temperature
            try:
                temp_result = await self.get_temperature()
                if temp_result['success'] and 'temperature' in temp_result:
                    temp = temp_result['temperature']
                    health_data['temperature'] = {
                        'value': temp,
                        'status': 'normal' if temp < 60 else 'warning' if temp < 70 else 'critical',
                        'unit': 'celsius'
                    }
                    
                    if temp >= 70:
                        issues.append(f'High temperature: {temp}°C')
                else:
                    health_data['temperature'] = {'status': 'unavailable'}
                    
            except Exception as e:
                health_data['temperature'] = {'status': 'error', 'error': str(e)}
            
            # Get system information
            try:
                tasks = [
                    self.get_serial_number(),
                    self.get_model_number(),
                    self.get_software_version()
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    if isinstance(result, dict) and result.get('success'):
                        if i == 0 and 'serial_number' in result:
                            health_data['system_info']['serial_number'] = result['serial_number']
                        elif i == 1 and 'model_number' in result:
                            health_data['system_info']['model_number'] = result['model_number']
                        elif i == 2 and 'software_version' in result:
                            health_data['system_info']['software_version'] = result['software_version']
                            
            except Exception as e:
                logger.debug(f"System info gathering failed: {e}")
            
            # Determine overall health
            if len(issues) == 0:
                health_data['overall_health'] = 'healthy'
            elif any('critical' in issue.lower() or 'failed' in issue.lower() for issue in issues):
                health_data['overall_health'] = 'critical'
            else:
                health_data['overall_health'] = 'warning'
            
            health_data['issues'] = issues
            
        except Exception as e:
            logger.error(f"Health check failed for display {self.display_id}: {e}")
            health_data['overall_health'] = 'error'
            health_data['error'] = str(e)
        
        return health_data

# Database Management
def init_database():
    """Initialize SQLite database for the video wall system"""
    db_path = Path('samsung_video_wall.db')
    
    with sqlite3.connect(db_path) as conn:
        # Display status table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS display_status (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                model TEXT DEFAULT 'LH55BECHLGFXGO',
                online BOOLEAN DEFAULT 0,
                responsive BOOLEAN DEFAULT 0,
                power BOOLEAN DEFAULT 0,
                volume INTEGER DEFAULT 50,
                muted BOOLEAN DEFAULT 0,
                input_source TEXT DEFAULT 'HDMI1',
                picture_mode TEXT DEFAULT 'STANDARD',
                brightness INTEGER DEFAULT 50,
                contrast INTEGER DEFAULT 50,
                temperature INTEGER,
                serial_number TEXT,
                software_version TEXT,
                current_content TEXT,
                video_wall_enabled BOOLEAN DEFAULT 0,
                grid_position TEXT,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_count INTEGER DEFAULT 0
            )
        ''')
        
        # Content library table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS content_library (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                thumbnail TEXT,
                duration INTEGER,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Deployment log table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS deployment_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_id INTEGER,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                content_id TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Scheduled tasks table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY,
                display_ids TEXT NOT NULL,
                content_id TEXT NOT NULL,
                action TEXT NOT NULL,
                schedule_time TIMESTAMP NOT NULL,
                repeat_pattern TEXT,
                enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP,
                next_run TIMESTAMP
            )
        ''')
        
        # System configuration table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Video wall layouts table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS video_wall_layouts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                grid_width INTEGER NOT NULL,
                grid_height INTEGER NOT NULL,
                display_mapping TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT 0
            )
        ''')
        
        conn.commit()
        
    logger.info(f"Database initialized: {db_path}")

@contextmanager
def get_db():
    """Database context manager"""
    conn = sqlite3.connect('samsung_video_wall.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Configuration Management
class VideoWallConfig:
    """Configuration management for Samsung LH55BECHLGFXGO Video Wall"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        self.config_file = Path(config_file)
        self.config = self._load_default_config()
        self.load_config()
    
    def _load_default_config(self) -> Dict:
        """Load default configuration"""
        return {
            'system': {
                'name': 'Samsung LH55BECHLGFXGO Video Wall',
                'version': '1.0.0',
                'debug': False
            },
            'displays': {},
            'server': {
                'host': '0.0.0.0',
                'port': 5000,
                'secret_key': 'samsung-lh55bechlgfxgo-control'
            },
            'magicinfo': {
                'enabled': False,
                'server_url': '',
                'username': '',
                'password': '',
                'api_key': ''
            },
            'optisigns': {
                'enabled': False,
                'server_url': '',
                'api_key': '',
                'username': '',
                'password': ''
            },
            'content': {
                'static_path': './static_content',
                'upload_path': './uploads',
                'max_file_size_mb': 500,
                'allowed_extensions': ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.avi', '.mov', '.webm', '.html']
            },
            'monitoring': {
                'health_check_interval': 30,
                'temperature_warning_threshold': 60,
                'temperature_critical_threshold': 70,
                'max_error_count': 5
            },
            'video_wall': {
                'enabled': False,
                'default_layout': '2x2',
                'bezel_compensation': True,
                'auto_power_management': True
            }
        }
    
    def load_config(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    file_config = yaml.safe_load(f)
                
                # Merge with defaults
                self._deep_merge(self.config, file_config)
                logger.info(f"Configuration loaded from {self.config_file}")
                
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        else:
            logger.info("No config file found, using defaults")
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, indent=2)
            
            logger.info(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    def _deep_merge(self, target: Dict, source: Dict):
        """Deep merge two dictionaries"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value
    
    def get(self, key_path: str, default=None):
        """Get configuration value using dot notation"""
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def set(self, key_path: str, value):
        """Set configuration value using dot notation"""
        keys = key_path.split('.')
        target = self.config
        
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        
        target[keys[-1]] = value

# Global instances
config = VideoWallConfig()
display_controllers: Dict[int, SamsungLH55BECHLGFXGOController] = {}

# Initialize display controllers from config
def initialize_displays():
    """Initialize display controllers from configuration"""
    global display_controllers
    
    displays_config = config.get('displays', {})
    
    for display_id, display_config in displays_config.items():
        try:
            controller = SamsungLH55BECHLGFXGOController(
                display_id=int(display_id),
                ip=display_config['ip'],
                port=display_config.get('port', 1515)
            )
            
            controller.status.name = display_config.get('name', f'LH55BECHLGFXGO-{display_id}')
            display_controllers[int(display_id)] = controller
            
        except Exception as e:
            logger.error(f"Failed to initialize display {display_id}: {e}")
    
    logger.info(f"Initialized {len(display_controllers)} Samsung LH55BECHLGFXGO displays")

if __name__ == "__main__":
    # Initialize system
    init_database()
    initialize_displays()
    
    logger.info("Samsung LH55BECHLGFXGO Video Wall Control System starting...")
    
    # This is the foundation - the API endpoints and web interface will be added next
    print("Samsung LH55BECHLGFXGO Video Wall Control System")
    print("=" * 50)
    print(f"Model: {LH55BECHLGFXGOSpecs().model}")
    print(f"Display Count: {len(display_controllers)}")
    print(f"Configuration: {config.config_file}")
    print("System ready for API and web interface integration...")
