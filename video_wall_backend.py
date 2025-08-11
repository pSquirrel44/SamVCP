#!/usr/bin/env python3
"""
Video Wall Control Panel Backend Server
Supports Samsung MagicInfo, OptiSigns, and generic display control
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import asyncio
import aiohttp
import serial
import socket
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
import requests
from pathlib import Path
import schedule
import sqlite3
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'video-wall-control-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
CONFIG = {
    'displays': {
        1: {'name': 'Display 1 - Main', 'ip': '192.168.1.101', 'port': 1515, 'protocol': 'tcp'},
        2: {'name': 'Display 2 - Left', 'ip': '192.168.1.102', 'port': 1515, 'protocol': 'tcp'},
        3: {'name': 'Display 3 - Right', 'ip': '192.168.1.103', 'port': 1515, 'protocol': 'tcp'},
        4: {'name': 'Display 4 - Bottom', 'ip': '192.168.1.104', 'port': 1515, 'protocol': 'tcp'}
    },
    'magicinfo': {
        'server_url': 'http://192.168.1.200:7001',
        'username': 'admin',
        'password': 'admin123',
        'api_key': 'your-magicinfo-api-key'
    },
    'optisigns': {
        'server_url': 'http://192.168.1.201:8080',
        'api_key': 'your-optisigns-api-key',
        'username': 'admin',
        'password': 'admin123'
    },
    'content': {
        'static_path': './static_content/',
        'streaming_sources': {
            'rtmp_server': 'rtmp://192.168.1.205/live/',
            'youtube_api_key': 'your-youtube-api-key'
        }
    }
}

# Data Models
@dataclass
class DisplayStatus:
    id: int
    name: str
    online: bool
    power: bool
    volume: int
    input_source: str
    current_content: Optional[str]
    last_update: datetime
    temperature: Optional[int] = None
    error_status: Optional[str] = None

@dataclass
class ContentItem:
    id: str
    name: str
    type: str  # 'image', 'video', 'stream', 'webpage'
    url: str
    duration: Optional[int] = None
    thumbnail: Optional[str] = None

@dataclass
class ScheduledContent:
    id: str
    content_id: str
    display_ids: List[int]
    start_time: datetime
    end_time: Optional[datetime]
    repeat: Optional[str] = None  # 'daily', 'weekly', 'monthly'

# Database setup
def init_database():
    with sqlite3.connect('video_wall.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS display_status (
                id INTEGER PRIMARY KEY,
                name TEXT,
                online BOOLEAN,
                power BOOLEAN,
                volume INTEGER,
                input_source TEXT,
                current_content TEXT,
                last_update TIMESTAMP,
                temperature INTEGER,
                error_status TEXT
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS content_library (
                id TEXT PRIMARY KEY,
                name TEXT,
                type TEXT,
                url TEXT,
                duration INTEGER,
                thumbnail TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_content (
                id TEXT PRIMARY KEY,
                content_id TEXT,
                display_ids TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                repeat_pattern TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS deployment_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_id INTEGER,
                content_id TEXT,
                action TEXT,
                status TEXT,
                timestamp TIMESTAMP,
                details TEXT
            )
        ''')

@contextmanager
def get_db():
    conn = sqlite3.connect('video_wall.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Display Control Classes
class DisplayController:
    def __init__(self, display_id: int, config: dict):
        self.display_id = display_id
        self.config = config
        self.status = DisplayStatus(
            id=display_id,
            name=config['name'],
            online=False,
            power=False,
            volume=50,
            input_source='network',
            current_content=None,
            last_update=datetime.now()
        )

    async def check_connection(self) -> bool:
        """Check if display is reachable"""
        try:
            if self.config['protocol'] == 'tcp':
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.config['ip'], self.config['port']),
                    timeout=5.0
                )
                writer.close()
                await writer.wait_closed()
                self.status.online = True
                return True
        except Exception as e:
            logger.warning(f"Display {self.display_id} connection failed: {e}")
            self.status.online = False
            return False

    async def send_command(self, command: str, data: Any = None) -> dict:
        """Send command to display"""
        try:
            if not self.status.online:
                await self.check_connection()
            
            if self.config['protocol'] == 'tcp':
                return await self._send_tcp_command(command, data)
            elif self.config['protocol'] == 'serial':
                return await self._send_serial_command(command, data)
            else:
                return {'success': False, 'error': 'Unsupported protocol'}
                
        except Exception as e:
            logger.error(f"Command failed for display {self.display_id}: {e}")
            return {'success': False, 'error': str(e)}

    async def _send_tcp_command(self, command: str, data: Any) -> dict:
        """Send TCP command to Samsung display (MDC protocol)"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.config['ip'], self.config['port']),
                timeout=5.0
            )

            # Samsung MDC protocol commands
            mdc_commands = {
                'power_on': bytes([0xAA, 0x11, self.display_id, 0x01, 0x01, 0x14]),
                'power_off': bytes([0xAA, 0x11, self.display_id, 0x01, 0x00, 0x13]),
                'volume_set': lambda vol: bytes([0xAA, 0x12, self.display_id, 0x01, vol, 0x14 + vol]),
                'input_hdmi1': bytes([0xAA, 0x14, self.display_id, 0x01, 0x21, 0x51]),
                'input_hdmi2': bytes([0xAA, 0x14, self.display_id, 0x01, 0x23, 0x53]),
                'input_network': bytes([0xAA, 0x14, self.display_id, 0x01, 0x60, 0x90]),
            }

            cmd_data = None
            if command == 'power':
                cmd_data = mdc_commands['power_on'] if data == 'on' else mdc_commands['power_off']
                self.status.power = data == 'on'
            elif command == 'volume':
                cmd_data = mdc_commands['volume_set'](int(data))
                self.status.volume = int(data)
            elif command == 'input':
                input_map = {
                    'hdmi1': 'input_hdmi1',
                    'hdmi2': 'input_hdmi2',
                    'network': 'input_network'
                }
                cmd_data = mdc_commands.get(input_map.get(data))
                if cmd_data:
                    self.status.input_source = data

            if cmd_data:
                writer.write(cmd_data)
                await writer.drain()
                
                # Read response
                response = await asyncio.wait_for(reader.read(1024), timeout=3.0)
                
            writer.close()
            await writer.wait_closed()
            
            self.status.last_update = datetime.now()
            await self._update_database()
            
            return {'success': True, 'message': f'Command {command} executed successfully'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _send_serial_command(self, command: str, data: Any) -> dict:
        """Send serial command for displays that use RS232"""
        # Implementation for RS232 control
        # This would be used for older displays or specific protocols
        pass

    async def _update_database(self):
        """Update display status in database"""
        with get_db() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO display_status 
                (id, name, online, power, volume, input_source, current_content, last_update, temperature, error_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.status.id, self.status.name, self.status.online, self.status.power,
                self.status.volume, self.status.input_source, self.status.current_content,
                self.status.last_update, self.status.temperature, self.status.error_status
            ))
            conn.commit()

class MagicInfoController:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.token = None

    async def authenticate(self) -> bool:
        """Authenticate with MagicInfo server"""
        try:
            auth_url = f"{self.config['server_url']}/api/auth/login"
            auth_data = {
                'username': self.config['username'],
                'password': self.config['password']
            }
            
            response = self.session.post(auth_url, json=auth_data)
            if response.status_code == 200:
                self.token = response.json().get('token')
                self.session.headers.update({'Authorization': f'Bearer {self.token}'})
                return True
            return False
        except Exception as e:
            logger.error(f"MagicInfo authentication failed: {e}")
            return False

    async def get_channels(self) -> List[dict]:
        """Get available MagicInfo channels"""
        try:
            if not self.token:
                await self.authenticate()
            
            response = self.session.get(f"{self.config['server_url']}/api/channels")
            if response.status_code == 200:
                return response.json().get('channels', [])
            return []
        except Exception as e:
            logger.error(f"Failed to get MagicInfo channels: {e}")
            return []

    async def deploy_content(self, display_ids: List[int], channel_id: str) -> dict:
        """Deploy content to displays via MagicInfo"""
        try:
            deploy_url = f"{self.config['server_url']}/api/content/deploy"
            deploy_data = {
                'channel_id': channel_id,
                'display_ids': display_ids,
                'immediate': True
            }
            
            response = self.session.post(deploy_url, json=deploy_data)
            return {'success': response.status_code == 200, 'data': response.json()}
        except Exception as e:
            logger.error(f"MagicInfo deployment failed: {e}")
            return {'success': False, 'error': str(e)}

class OptiSignsController:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.api_key = config['api_key']

    async def get_playlists(self) -> List[dict]:
        """Get OptiSigns playlists"""
        try:
            headers = {'X-API-Key': self.api_key}
            response = self.session.get(
                f"{self.config['server_url']}/api/playlists",
                headers=headers
            )
            if response.status_code == 200:
                return response.json().get('playlists', [])
            return []
        except Exception as e:
            logger.error(f"Failed to get OptiSigns playlists: {e}")
            return []

    async def deploy_playlist(self, display_ids: List[int], playlist_id: str) -> dict:
        """Deploy playlist to displays"""
        try:
            headers = {'X-API-Key': self.api_key}
            deploy_data = {
                'playlist_id': playlist_id,
                'device_ids': display_ids
            }
            
            response = self.session.post(
                f"{self.config['server_url']}/api/deploy",
                json=deploy_data,
                headers=headers
            )
            return {'success': response.status_code == 200, 'data': response.json()}
        except Exception as e:
            logger.error(f"OptiSigns deployment failed: {e}")
            return {'success': False, 'error': str(e)}

# Global instances
display_controllers = {
    display_id: DisplayController(display_id, config)
    for display_id, config in CONFIG['displays'].items()
}
magicinfo_controller = MagicInfoController(CONFIG['magicinfo'])
optisigns_controller = OptiSignsController(CONFIG['optisigns'])

# API Routes
@app.route('/api/displays/<int:display_id>/power', methods=['POST'])
async def control_power(display_id):
    """Control display power"""
    try:
        data = request.get_json()
        action = data.get('action')  # 'on', 'off', 'toggle'
        
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        controller = display_controllers[display_id]
        
        if action == 'toggle':
            action = 'off' if controller.status.power else 'on'
        
        result = await controller.send_command('power', action)
        
        # Log the action
        with get_db() as conn:
            conn.execute('''
                INSERT INTO deployment_log (display_id, action, status, timestamp, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (display_id, f'power_{action}', 'success' if result['success'] else 'failed', 
                  datetime.now(), json.dumps(result)))
            conn.commit()
        
        # Emit status update via WebSocket
        socketio.emit('display_status_update', {
            'display_id': display_id,
            'status': asdict(controller.status)
        })
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Power control error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/volume', methods=['POST'])
async def control_volume(display_id):
    """Control display volume"""
    try:
        data = request.get_json()
        volume = data.get('volume')
        
        if not (0 <= volume <= 100):
            return jsonify({'success': False, 'error': 'Volume must be between 0-100'}), 400
        
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        controller = display_controllers[display_id]
        result = await controller.send_command('volume', volume)
        
        socketio.emit('display_status_update', {
            'display_id': display_id,
            'status': asdict(controller.status)
        })
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/input', methods=['POST'])
async def control_input(display_id):
    """Control display input source"""
    try:
        data = request.get_json()
        input_source = data.get('input')
        
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        controller = display_controllers[display_id]
        result = await controller.send_command('input', input_source)
        
        socketio.emit('display_status_update', {
            'display_id': display_id,
            'status': asdict(controller.status)
        })
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/status', methods=['GET'])
async def get_display_status(display_id):
    """Get display status"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        controller = display_controllers[display_id]
        await controller.check_connection()
        
        return jsonify({
            'success': True,
            'status': asdict(controller.status)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/status', methods=['GET'])
async def get_all_display_status():
    """Get status of all displays"""
    try:
        statuses = {}
        for display_id, controller in display_controllers.items():
            await controller.check_connection()
            statuses[display_id] = asdict(controller.status)
        
        return jsonify({
            'success': True,
            'displays': statuses
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/content/deploy', methods=['POST'])
async def deploy_content():
    """Deploy content to selected displays"""
    try:
        data = request.get_json()
        display_ids = data.get('displayIds', [])
        content = data.get('content', {})
        
        results = {}
        
        for display_id in display_ids:
            if display_id not in display_controllers:
                results[display_id] = {'success': False, 'error': 'Display not found'}
                continue
            
            controller = display_controllers[display_id]
            
            # Handle different content types
            if content['type'] == 'magicinfo':
                result = await magicinfo_controller.deploy_content([display_id], content['identifier'])
            elif content['type'] == 'optisigns':
                result = await optisigns_controller.deploy_playlist([display_id], content['identifier'])
            elif content['type'] == 'custom':
                # Deploy custom URL content
                result = await deploy_custom_content(display_id, content)
            else:
                # Handle static content
                result = await deploy_static_content(display_id, content)
            
            results[display_id] = result
            
            # Update display status
            if result['success']:
                controller.status.current_content = content['identifier']
                await controller._update_database()
            
            # Log deployment
            with get_db() as conn:
                conn.execute('''
                    INSERT INTO deployment_log (display_id, content_id, action, status, timestamp, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (display_id, content['identifier'], 'deploy', 
                      'success' if result['success'] else 'failed',
                      datetime.now(), json.dumps(result)))
                conn.commit()
        
        # Emit update via WebSocket
        socketio.emit('content_deployed', {
            'display_ids': display_ids,
            'content': content,
            'results': results
        })
        
        return jsonify({
            'success': True,
            'results': results
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

async def deploy_custom_content(display_id: int, content: dict) -> dict:
    """Deploy custom URL content to display"""
    try:
        controller = display_controllers[display_id]
        
        # For custom content, we typically send a URL to the display
        # This depends on your display's web browser capabilities
        url = content['identifier']
        
        if content.get('urlType') == 'stream':
            # Handle streaming URLs (RTMP, HLS, etc.)
            result = await controller.send_command('stream_url', url)
        else:
            # Handle web pages and images
            result = await controller.send_command('web_url', url)
        
        return result
    
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def deploy_static_content(display_id: int, content: dict) -> dict:
    """Deploy static content to display"""
    try:
        controller = display_controllers[display_id]
        
        # Static content is typically served from a local web server
        content_url = f"http://{request.host}/static/{content['identifier']}"
        result = await controller.send_command('web_url', content_url)
        
        return result
    
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.route('/api/magicinfo/channels', methods=['GET'])
async def get_magicinfo_channels():
    """Get MagicInfo channels"""
    try:
        channels = await magicinfo_controller.get_channels()
        return jsonify({
            'success': True,
            'channels': channels
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/optisigns/playlists', methods=['GET'])
async def get_optisigns_playlists():
    """Get OptiSigns playlists"""
    try:
        playlists = await optisigns_controller.get_playlists()
        return jsonify({
            'success': True,
            'playlists': playlists
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/content/schedule', methods=['POST'])
async def schedule_content():
    """Schedule content deployment"""
    try:
        data = request.get_json()
        
        scheduled_item = ScheduledContent(
            id=f"schedule_{int(time.time())}",
            content_id=data['content_id'],
            display_ids=data['display_ids'],
            start_time=datetime.fromisoformat(data['start_time']),
            end_time=datetime.fromisoformat(data['end_time']) if data.get('end_time') else None,
            repeat=data.get('repeat')
        )
        
        # Save to database
        with get_db() as conn:
            conn.execute('''
                INSERT INTO scheduled_content 
                (id, content_id, display_ids, start_time, end_time, repeat_pattern, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                scheduled_item.id, scheduled_item.content_id, 
                json.dumps(scheduled_item.display_ids),
                scheduled_item.start_time, scheduled_item.end_time,
                scheduled_item.repeat, datetime.now()
            ))
            conn.commit()
        
        # Schedule the job
        schedule_deployment_job(scheduled_item)
        
        return jsonify({'success': True, 'schedule_id': scheduled_item.id})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def schedule_deployment_job(scheduled_item: ScheduledContent):
    """Schedule a deployment job"""
    def job():
        asyncio.run(execute_scheduled_deployment(scheduled_item))
    
    # Convert to schedule library format
    start_time = scheduled_item.start_time.strftime('%H:%M')
    
    if scheduled_item.repeat == 'daily':
        schedule.every().day.at(start_time).do(job)
    elif scheduled_item.repeat == 'weekly':
        day_name = scheduled_item.start_time.strftime('%A').lower()
        getattr(schedule.every(), day_name).at(start_time).do(job)
    else:
        # One-time schedule
        schedule.every().day.at(start_time).do(job).tag(scheduled_item.id)

async def execute_scheduled_deployment(scheduled_item: ScheduledContent):
    """Execute a scheduled content deployment"""
    try:
        # Get content details from database
        with get_db() as conn:
            content_row = conn.execute(
                'SELECT * FROM content_library WHERE id = ?',
                (scheduled_item.content_id,)
            ).fetchone()
        
        if not content_row:
            logger.error(f"Content {scheduled_item.content_id} not found for scheduled deployment")
            return
        
        content = {
            'type': content_row['type'],
            'identifier': content_row['id'],
            'url': content_row['url']
        }
        
        # Deploy to all specified displays
        results = {}
        for display_id in scheduled_item.display_ids:
            if display_id in display_controllers:
                if content['type'] == 'magicinfo':
                    result = await magicinfo_controller.deploy_content([display_id], content['identifier'])
                elif content['type'] == 'optisigns':
                    result = await optisigns_controller.deploy_playlist([display_id], content['identifier'])
                else:
                    result = await deploy_static_content(display_id, content)
                
                results[display_id] = result
        
        # Log the scheduled deployment
        with get_db() as conn:
            for display_id, result in results.items():
                conn.execute('''
                    INSERT INTO deployment_log (display_id, content_id, action, status, timestamp, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (display_id, scheduled_item.content_id, 'scheduled_deploy',
                      'success' if result['success'] else 'failed',
                      datetime.now(), json.dumps(result)))
            conn.commit()
        
        logger.info(f"Scheduled deployment {scheduled_item.id} completed")
        
    except Exception as e:
        logger.error(f"Scheduled deployment failed: {e}")

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('connected', {'message': 'Connected to Video Wall Control Server'})
    logger.info('Client connected')

@socketio.on('request_status_update')
def handle_status_request():
    """Handle status update request"""
    async def send_status():
        statuses = {}
        for display_id, controller in display_controllers.items():
            await controller.check_connection()
            statuses[display_id] = asdict(controller.status)
        
        emit('all_display_status', statuses)
    
    asyncio.run(send_status())

# Background Tasks
def run_scheduler():
    """Run scheduled jobs"""
    while True:
        schedule.run_pending()
        time.sleep(1)

def monitor_displays():
    """Monitor display health"""
    async def check_all_displays():
        while True:
            for display_id, controller in display_controllers.items():
                try:
                    await controller.check_connection()
                    # You could add temperature monitoring, error checking, etc.
                except Exception as e:
                    logger.error(f"Health check failed for display {display_id}: {e}")
            
            await asyncio.sleep(60)  # Check every minute
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_all_displays())

# Initialize application
def initialize_app():
    """Initialize the application"""
    init_database()
    
    # Start background threads
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    monitor_thread = threading.Thread(target=monitor_displays, daemon=True)
    monitor_thread.start()
    
    logger.info("Video Wall Control Server initialized")

# Health check endpoint
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'displays_count': len(display_controllers)
    })

# Configuration endpoint
@app.route('/api/config', methods=['GET'])
def get_config():
    """Get system configuration"""
    return jsonify({
        'displays': CONFIG['displays'],
        'content_sources': {
            'magicinfo_enabled': bool(CONFIG['magicinfo']['server_url']),
            'optisigns_enabled': bool(CONFIG['optisigns']['server_url']),
            'static_content_path': CONFIG['content']['static_path']
        }
    })

if __name__ == '__main__':
    initialize_app()
    
    # Run with SocketIO support
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=False,
        allow_unsafe_werkzeug=True
    )