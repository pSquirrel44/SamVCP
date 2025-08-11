#!/usr/bin/env python3
"""
Samsung LH55BECHLGFXGO Video Wall Control System - API Endpoints
Add these to your main application file
"""

# API Routes for Samsung LH55BECHLGFXGO Control

# ============================================================================
# DISPLAY CONTROL ENDPOINTS
# ============================================================================

@app.route('/api/displays', methods=['GET'])
async def get_all_displays():
    """Get all Samsung LH55BECHLGFXGO displays"""
    try:
        displays = {}
        
        for display_id, controller in display_controllers.items():
            # Get current status
            if controller.status.online:
                health = await controller.health_check()
            else:
                health = controller.status.to_dict()
                
            displays[display_id] = {
                'id': display_id,
                'name': controller.status.name,
                'model': 'LH55BECHLGFXGO',
                'ip': controller.ip,
                'status': health,
                'specs': asdict(controller.specs)
            }
        
        return jsonify({
            'success': True,
            'total_displays': len(displays),
            'displays': displays,
            'model_info': {
                'series': 'Samsung BEC Series',
                'model': 'LH55BECHLGFXGO',
                'screen_size': '55 inch',
                'resolution': '1920x1080'
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get displays: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>', methods=['GET'])
async def get_display_details(display_id):
    """Get detailed information about specific Samsung LH55BECHLGFXGO display"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        controller = display_controllers[display_id]
        
        # Comprehensive health check
        health_data = await controller.health_check()
        
        # Get additional information
        display_info = {
            'basic_info': {
                'id': display_id,
                'name': controller.status.name,
                'model': 'LH55BECHLGFXGO',
                'ip': controller.ip,
                'port': controller.port
            },
            'specifications': asdict(controller.specs),
            'current_status': controller.status.to_dict(),
            'health_check': health_data,
            'capabilities': {
                'video_wall_support': True,
                'max_grid_size': '10x10',
                'input_sources': controller.specs.supported_inputs,
                'network_control': True,
                'temperature_monitoring': True,
                'power_management': True
            }
        }
        
        return jsonify({
            'success': True,
            'display': display_info
        })
        
    except Exception as e:
        logger.error(f"Failed to get display {display_id} details: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/power', methods=['POST'])
async def control_display_power(display_id):
    """Control Samsung LH55BECHLGFXGO power"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        data = request.get_json()
        action = data.get('action', '').lower()
        
        controller = display_controllers[display_id]
        
        if action == 'on':
            result = await controller.power_on()
        elif action == 'off':
            result = await controller.power_off()
        elif action == 'toggle':
            # Get current status first
            status_result = await controller.get_power_status()
            if status_result['success']:
                if status_result.get('power_on'):
                    result = await controller.power_off()
                else:
                    result = await controller.power_on()
            else:
                result = {'success': False, 'error': 'Could not determine current power state'}
        elif action == 'status':
            result = await controller.get_power_status()
        else:
            return jsonify({'success': False, 'error': 'Invalid action. Use: on, off, toggle, status'}), 400
        
        # Log the action
        if result['success']:
            with get_db() as conn:
                conn.execute('''
                    INSERT INTO deployment_log (display_id, action, status, details, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (display_id, f'power_{action}', 'success', json.dumps(result), datetime.now()))
                conn.commit()
        
        # Emit real-time update
        socketio.emit('display_update', {
            'display_id': display_id,
            'action': f'power_{action}',
            'result': result,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Power control failed for display {display_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/volume', methods=['POST'])
async def control_display_volume(display_id):
    """Control Samsung LH55BECHLGFXGO volume"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        data = request.get_json()
        volume = data.get('volume')
        mute = data.get('mute')
        
        controller = display_controllers[display_id]
        results = {}
        
        if volume is not None:
            if not isinstance(volume, int) or not 0 <= volume <= 100:
                return jsonify({'success': False, 'error': 'Volume must be integer 0-100'}), 400
            
            volume_result = await controller.set_volume(volume)
            results['volume'] = volume_result
        
        if mute is not None:
            if not isinstance(mute, bool):
                return jsonify({'success': False, 'error': 'Mute must be boolean'}), 400
            
            mute_result = await controller.set_mute(mute)
            results['mute'] = mute_result
        
        # Check if any operation was requested
        if not results:
            return jsonify({'success': False, 'error': 'No volume or mute action specified'}), 400
        
        # Determine overall success
        overall_success = all(r.get('success', False) for r in results.values())
        
        # Emit real-time update
        socketio.emit('display_update', {
            'display_id': display_id,
            'action': 'volume_control',
            'result': results,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': overall_success,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Volume control failed for display {display_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/input', methods=['POST'])
async def control_display_input(display_id):
    """Control Samsung LH55BECHLGFXGO input source"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        data = request.get_json()
        input_source = data.get('input', '').upper()
        
        # Validate input source
        try:
            source_enum = InputSource[input_source]
        except KeyError:
            valid_inputs = [source.name for source in InputSource]
            return jsonify({
                'success': False, 
                'error': f'Invalid input source. Valid options: {valid_inputs}'
            }), 400
        
        controller = display_controllers[display_id]
        result = await controller.set_input_source(source_enum)
        
        # Emit real-time update
        socketio.emit('display_update', {
            'display_id': display_id,
            'action': 'input_change',
            'input_source': input_source,
            'result': result,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Input control failed for display {display_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/<int:display_id>/picture', methods=['POST'])
async def control_display_picture(display_id):
    """Control Samsung LH55BECHLGFXGO picture settings"""
    try:
        if display_id not in display_controllers:
            return jsonify({'success': False, 'error': 'Display not found'}), 404
        
        data = request.get_json()
        controller = display_controllers[display_id]
        results = {}
        
        # Picture mode
        if 'mode' in data:
            mode = data['mode'].upper()
            try:
                mode_enum = PictureMode[mode]
                results['picture_mode'] = await controller.set_picture_mode(mode_enum)
            except KeyError:
                valid_modes = [mode.name for mode in PictureMode]
                return jsonify({
                    'success': False, 
                    'error': f'Invalid picture mode. Valid options: {valid_modes}'
                }), 400
        
        # Brightness
        if 'brightness' in data:
            brightness = data['brightness']
            if not isinstance(brightness, int) or not 0 <= brightness <= 100:
                return jsonify({'success': False, 'error': 'Brightness must be integer 0-100'}), 400
            results['brightness'] = await controller.set_brightness(brightness)
        
        # Contrast
        if 'contrast' in data:
            contrast = data['contrast']
            if not isinstance(contrast, int) or not 0 <= contrast <= 100:
                return jsonify({'success': False, 'error': 'Contrast must be integer 0-100'}), 400
            results['contrast'] = await controller.set_contrast(contrast)
        
        if not results:
            return jsonify({'success': False, 'error': 'No picture settings specified'}), 400
        
        overall_success = all(r.get('success', False) for r in results.values())
        
        return jsonify({
            'success': overall_success,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Picture control failed for display {display_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# VIDEO WALL MANAGEMENT ENDPOINTS
# ============================================================================

@app.route('/api/video-wall/layouts', methods=['GET'])
def get_video_wall_layouts():
    """Get available video wall layouts for Samsung LH55BECHLGFXGO"""
    try:
        display_count = len(display_controllers)
        
        if display_count == 0:
            return jsonify({'success': False, 'error': 'No displays configured'}), 400
        
        layouts = {}
        
        # Generate possible layouts
        for h in range(1, min(display_count + 1, 11)):  # Max 10x10 for LH55BECHLGFXGO
            if display_count % h == 0:
                v = display_count // h
                if v <= 10:  # Max 10x10 grid
                    layout_name = f"{h}x{v}"
                    
                    # Calculate display mapping
                    display_mapping = {}
                    display_ids = list(display_controllers.keys())
                    
                    for i, display_id in enumerate(display_ids[:h * v]):
                        h_pos = (i % h) + 1
                        v_pos = (i // h) + 1
                        
                        display_mapping[display_id] = {
                            'horizontal_position': h_pos,
                            'vertical_position': v_pos,
                            'display_name': display_controllers[display_id].status.name
                        }
                    
                    layouts[layout_name] = {
                        'name': layout_name,
                        'description': f'{h} × {v} Samsung LH55BECHLGFXGO Video Wall',
                        'horizontal': h,
                        'vertical': v,
                        'total_displays': h * v,
                        'aspect_ratio': round(h / v, 2),
                        'total_resolution': f"{1920 * h}x{1080 * v}",
                        'display_mapping': display_mapping,
                        'bezel_compensation': config.get('video_wall.bezel_compensation', True)
                    }
        
        # Get current active layout
        current_layout = None
        with get_db() as conn:
            result = conn.execute('''
                SELECT * FROM video_wall_layouts 
                WHERE active = 1 
                ORDER BY created_at DESC 
                LIMIT 1
            ''').fetchone()
            
            if result:
                current_layout = dict(result)
        
        return jsonify({
            'success': True,
            'available_layouts': layouts,
            'current_layout': current_layout,
            'display_count': display_count,
            'max_grid_size': '10x10',
            'model_support': 'Samsung LH55BECHLGFXGO supports up to 10x10 video wall'
        })
        
    except Exception as e:
        logger.error(f"Failed to get video wall layouts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/video-wall/apply', methods=['POST'])
async def apply_video_wall_layout():
    """Apply video wall layout to Samsung LH55BECHLGFXGO displays"""
    try:
        data = request.get_json()
        layout_name = data.get('layout_name')
        
        if not layout_name:
            return jsonify({'success': False, 'error': 'Layout name required'}), 400
        
        # Parse layout name (e.g., "2x2")
        try:
            h, v = map(int, layout_name.split('x'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid layout name format'}), 400
        
        # Validate layout
        if h > 10 or v > 10:
            return jsonify({'success': False, 'error': 'Samsung LH55BECHLGFXGO supports maximum 10x10 grid'}), 400
        
        if h * v > len(display_controllers):
            return jsonify({'success': False, 'error': 'Not enough displays for this layout'}), 400
        
        # Apply video wall configuration to each display
        results = {}
        display_ids = list(display_controllers.keys())[:h * v]
        
        for i, display_id in enumerate(display_ids):
            h_pos = (i % h) + 1
            v_pos = (i // h) + 1
            
            controller = display_controllers[display_id]
            
            try:
                result = await controller.set_video_wall_mode(
                    enabled=True,
                    h_monitors=h,
                    v_monitors=v,
                    h_position=h_pos,
                    v_position=v_pos
                )
                
                results[display_id] = {
                    'success': result['success'],
                    'position': f"{h_pos},{v_pos}",
                    'details': result
                }
                
                # Update database
                if result['success']:
                    with get_db() as conn:
                        conn.execute('''
                            UPDATE display_status 
                            SET video_wall_enabled = 1, grid_position = ?
                            WHERE id = ?
                        ''', (f"{h_pos},{v_pos}", display_id))
                        conn.commit()
                
            except Exception as e:
                results[display_id] = {
                    'success': False,
                    'error': str(e)
                }
        
        # Save layout to database
        layout_id = f"layout_{int(time.time())}"
        layout_data = {
            'name': layout_name,
            'description': f'{h}x{v} Samsung LH55BECHLGFXGO Video Wall',
            'grid_width': h,
            'grid_height': v,
            'display_mapping': {str(k): v for k, v in results.items() if v['success']}
        }
        
        with get_db() as conn:
            # Deactivate previous layouts
            conn.execute('UPDATE video_wall_layouts SET active = 0')
            
            # Insert new layout
            conn.execute('''
                INSERT INTO video_wall_layouts 
                (id, name, description, grid_width, grid_height, display_mapping, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (
                layout_id, 
                layout_data['name'],
                layout_data['description'],
                layout_data['grid_width'],
                layout_data['grid_height'],
                json.dumps(layout_data['display_mapping'])
            ))
            conn.commit()
        
        # Calculate success rate
        successful_displays = sum(1 for r in results.values() if r['success'])
        total_displays = len(results)
        
        # Emit real-time update
        socketio.emit('video_wall_update', {
            'action': 'layout_applied',
            'layout': layout_name,
            'results': results,
            'success_rate': successful_displays / total_displays,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': successful_displays == total_displays,
            'layout': layout_name,
            'applied_to_displays': successful_displays,
            'total_displays': total_displays,
            'results': results,
            'layout_id': layout_id
        })
        
    except Exception as e:
        logger.error(f"Failed to apply video wall layout: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/video-wall/disable', methods=['POST'])
async def disable_video_wall():
    """Disable video wall mode on all Samsung LH55BECHLGFXGO displays"""
    try:
        results = {}
        
        for display_id, controller in display_controllers.items():
            try:
                result = await controller.set_video_wall_mode(enabled=False)
                results[display_id] = result
                
                # Update database
                if result['success']:
                    with get_db() as conn:
                        conn.execute('''
                            UPDATE display_status 
                            SET video_wall_enabled = 0, grid_position = NULL
                            WHERE id = ?
                        ''', (display_id,))
                        conn.commit()
                        
            except Exception as e:
                results[display_id] = {'success': False, 'error': str(e)}
        
        # Deactivate layouts in database
        with get_db() as conn:
            conn.execute('UPDATE video_wall_layouts SET active = 0')
            conn.commit()
        
        successful_displays = sum(1 for r in results.values() if r['success'])
        total_displays = len(results)
        
        # Emit real-time update
        socketio.emit('video_wall_update', {
            'action': 'video_wall_disabled',
            'results': results,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': successful_displays == total_displays,
            'disabled_displays': successful_displays,
            'total_displays': total_displays,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Failed to disable video wall: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/video-wall/test', methods=['POST'])
async def test_video_wall_layout():
    """Test video wall layout with position indicators"""
    try:
        data = request.get_json()
        layout_name = data.get('layout_name')
        test_duration = data.get('duration', 10)  # seconds
        
        if not layout_name:
            return jsonify({'success': False, 'error': 'Layout name required'}), 400
        
        # Parse layout
        try:
            h, v = map(int, layout_name.split('x'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid layout name format'}), 400
        
        # Generate test pattern for each display
        results = {}
        display_ids = list(display_controllers.keys())[:h * v]
        
        for i, display_id in enumerate(display_ids):
            h_pos = (i % h) + 1
            v_pos = (i // h) + 1
            
            # Create test pattern HTML
            test_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        font-family: 'Arial', sans-serif;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        justify-content: center;
                        height: 100vh;
                        text-align: center;
                    }}
                    .test-container {{
                        background: rgba(255,255,255,0.1);
                        border-radius: 20px;
                        padding: 60px;
                        border: 3px solid white;
                        backdrop-filter: blur(10px);
                    }}
                    .position {{
                        font-size: 6rem;
                        font-weight: bold;
                        margin-bottom: 30px;
                        text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
                    }}
                    .grid-info {{
                        font-size: 3rem;
                        margin-bottom: 20px;
                        opacity: 0.9;
                    }}
                    .model-info {{
                        font-size: 2rem;
                        margin-bottom: 10px;
                        opacity: 0.8;
                    }}
                    .timer {{
                        font-size: 1.5rem;
                        margin-top: 30px;
                        opacity: 0.7;
                    }}
                    .coordinates {{
                        position: absolute;
                        top: 20px;
                        right: 20px;
                        font-size: 1.2rem;
                        background: rgba(0,0,0,0.3);
                        padding: 10px 15px;
                        border-radius: 10px;
                    }}
                </style>
                <script>
                    let timeLeft = {test_duration};
                    function updateTimer() {{
                        document.getElementById('timer').textContent = `Test ending in ${{timeLeft}}s`;
                        if (timeLeft <= 0) {{
                            document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-size:3rem;">Test Complete</div>';
                            return;
                        }}
                        timeLeft--;
                        setTimeout(updateTimer, 1000);
                    }}
                    window.onload = updateTimer;
                </script>
            </head>
            <body>
                <div class="coordinates">Display {display_id}</div>
                <div class="test-container">
                    <div class="position">Position {h_pos},{v_pos}</div>
                    <div class="grid-info">{layout_name} Video Wall</div>
                    <div class="model-info">Samsung LH55BECHLGFXGO</div>
                    <div class="model-info">55" Business Display</div>
                    <div class="timer" id="timer">Test starting...</div>
                </div>
            </body>
            </html>
            """
            
            # Save test file
            test_file = Path(f"test_pattern_display_{display_id}.html")
            try:
                with open(test_file, 'w') as f:
                    f.write(test_html)
                
                results[display_id] = {
                    'success': True,
                    'position': f"{h_pos},{v_pos}",
                    'test_file': str(test_file),
                    'message': f'Test pattern ready for display {display_id}'
                }
                
            except Exception as e:
                results[display_id] = {
                    'success': False,
                    'error': str(e)
                }
        
        return jsonify({
            'success': True,
            'layout': layout_name,
            'test_duration': test_duration,
            'results': results,
            'message': f'Test patterns generated for {layout_name} layout. Load the HTML files on each display.'
        })
        
    except Exception as e:
        logger.error(f"Failed to generate test patterns: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# BULK OPERATIONS ENDPOINTS
# ============================================================================

@app.route('/api/displays/bulk/power', methods=['POST'])
async def bulk_power_control():
    """Bulk power control for Samsung LH55BECHLGFXGO displays"""
    try:
        data = request.get_json()
        action = data.get('action', '').lower()
        display_ids = data.get('display_ids', list(display_controllers.keys()))
        
        if action not in ['on', 'off']:
            return jsonify({'success': False, 'error': 'Action must be "on" or "off"'}), 400
        
        # Validate display IDs
        invalid_ids = [id for id in display_ids if id not in display_controllers]
        if invalid_ids:
            return jsonify({'success': False, 'error': f'Invalid display IDs: {invalid_ids}'}), 400
        
        results = {}
        
        # Execute power commands
        for display_id in display_ids:
            try:
                controller = display_controllers[display_id]
                
                if action == 'on':
                    result = await controller.power_on()
                else:
                    result = await controller.power_off()
                
                results[display_id] = result
                
            except Exception as e:
                results[display_id] = {'success': False, 'error': str(e)}
        
        successful_count = sum(1 for r in results.values() if r.get('success'))
        
        # Log bulk operation
        with get_db() as conn:
            conn.execute('''
                INSERT INTO deployment_log (display_id, action, status, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (0, f'bulk_power_{action}', 'success', json.dumps({
                'display_ids': display_ids,
                'successful_count': successful_count,
                'results': results
            }), datetime.now()))
            conn.commit()
        
        return jsonify({
            'success': successful_count > 0,
            'action': f'bulk_power_{action}',
            'total_displays': len(display_ids),
            'successful_displays': successful_count,
            'failed_displays': len(display_ids) - successful_count,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Bulk power control failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/displays/bulk/volume', methods=['POST'])
async def bulk_volume_control():
    """Bulk volume control for Samsung LH55BECHLGFXGO displays"""
    try:
        data = request.get_json()
        volume = data.get('volume')
        mute = data.get('mute')
        display_ids = data.get('display_ids', list(display_controllers.keys()))
        
        if volume is None and mute is None:
            return jsonify({'success': False, 'error': 'Volume or mute parameter required'}), 400
        
        if volume is not None and (not isinstance(volume, int) or not 0 <= volume <= 100):
            return jsonify({'success': False, 'error': 'Volume must be integer 0-100'}), 400
        
        results = {}
        
        for display_id in display_ids:
            if display_id not in display_controllers:
                results[display_id] = {'success': False, 'error': 'Display not found'}
                continue
            
            try:
                controller = display_controllers[display_id]
                display_results = {}
                
                if volume is not None:
                    volume_result = await controller.set_volume(volume)
                    display_results['volume'] = volume_result
                
                if mute is not None:
                    mute_result = await controller.set_mute(mute)
                    display_results['mute'] = mute_result
                
                # Overall success for this display
                display_success = all(r.get('success', False) for r in display_results.values())
                results[display_id] = {
                    'success': display_success,
                    'operations': display_results
                }
                
            except Exception as e:
                results[display_id] = {'success': False, 'error': str(e)}
        
        successful_count = sum(1 for r in results.values() if r.get('success'))
        
        return jsonify({
            'success': successful_count > 0,
            'action': 'bulk_volume_control',
            'total_displays': len(display_ids),
            'successful_displays': successful_count,
            'failed_displays': len(display_ids) - successful_count,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Bulk volume control failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# MONITORING AND HEALTH ENDPOINTS
# ============================================================================

@app.route('/api/monitoring/health', methods=['GET'])
async def get_system_health():
    """Get comprehensive system health for Samsung LH55BECHLGFXGO displays"""
    try:
        health_summary = {
            'timestamp': datetime.now().isoformat(),
            'system_info': {
                'total_displays': len(display_controllers),
                'model': 'Samsung LH55BECHLGFXGO',
                'series': 'BEC Series'
            },
            'overall_status': 'unknown',
            'display_health': {},
            'statistics': {
                'online_count': 0,
                'responsive_count': 0,
                'powered_on_count': 0,
                'video_wall_enabled_count': 0,
                'average_temperature': 0,
                'total_errors': 0
            },
            'alerts': []
        }
        
        temperatures = []
        total_errors = 0
        
        # Check each display
        for display_id, controller in display_controllers.items():
            try:
                health_data = await controller.health_check()
                health_summary['display_health'][display_id] = health_data
                
                # Update statistics
                if health_data.get('connection', {}).get('status') == 'connected':
                    health_summary['statistics']['online_count'] += 1
                
                if health_data.get('power', {}).get('responsive'):
                    health_summary['statistics']['responsive_count'] += 1
                
                if health_data.get('power', {}).get('status') == 'on':
                    health_summary['statistics']['powered_on_count'] += 1
                
                if controller.status.video_wall_enabled:
                    health_summary['statistics']['video_wall_enabled_count'] += 1
                
                # Temperature tracking
                temp_data = health_data.get('temperature', {})
                if temp_data.get('value') is not None:
                    temp = temp_data['value']
                    temperatures.append(temp)
                    
                    # Temperature alerts
                    if temp >= 70:
                        health_summary['alerts'].append({
                            'level': 'critical',
                            'message': f'Display {display_id} temperature critical: {temp}°C',
                            'display_id': display_id,
                            'type': 'temperature'
                        })
                    elif temp >= 60:
                        health_summary['alerts'].append({
                            'level': 'warning',
                            'message': f'Display {display_id} temperature high: {temp}°C',
                            'display_id': display_id,
                            'type': 'temperature'
                        })
                
                # Error count
                error_count = health_data.get('connection', {}).get('error_count', 0)
                total_errors += error_count
                
                if error_count > 3:
                    health_summary['alerts'].append({
                        'level': 'warning',
                        'message': f'Display {display_id} has {error_count} connection errors',
                        'display_id': display_id,
                        'type': 'connectivity'
                    })
                
            except Exception as e:
                health_summary['display_health'][display_id] = {
                    'error': str(e),
                    'overall_health': 'error'
                }
                health_summary['alerts'].append({
                    'level': 'error',
                    'message': f'Health check failed for display {display_id}: {str(e)}',
                    'display_id': display_id,
                    'type': 'system'
                })
        
        # Calculate averages and overall status
        if temperatures:
            health_summary['statistics']['average_temperature'] = round(sum(temperatures) / len(temperatures), 1)
        
        health_summary['statistics']['total_errors'] = total_errors
        
        # Determine overall system status
        total_displays = len(display_controllers)
        online_rate = health_summary['statistics']['online_count'] / total_displays if total_displays > 0 else 0
        
        critical_alerts = len([a for a in health_summary['alerts'] if a['level'] == 'critical'])
        
        if critical_alerts > 0:
            health_summary['overall_status'] = 'critical'
        elif online_rate >= 0.9:
            health_summary['overall_status'] = 'healthy'
        elif online_rate >= 0.7:
            health_summary['overall_status'] = 'warning'
        else:
            health_summary['overall_status'] = 'critical'
        
        return jsonify({
            'success': True,
            'health': health_summary
        })
        
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/monitoring/alerts', methods=['GET'])
def get_system_alerts():
    """Get current system alerts"""
    try:
        level_filter = request.args.get('level')
        hours_back = request.args.get('hours', 24, type=int)
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        with get_db() as conn:
            query = '''
                SELECT * FROM deployment_log 
                WHERE timestamp > ? AND status IN ('error', 'failed', 'warning')
                ORDER BY timestamp DESC
            '''
            
            logs = conn.execute(query, (cutoff_time,)).fetchall()
            
            alerts = []
            for log in logs:
                alert_level = 'warning' if log['status'] == 'warning' else 'error'
                
                if level_filter and alert_level != level_filter:
                    continue
                
                alerts.append({
                    'id': log['id'],
                    'level': alert_level,
                    'message': f"Display {log['display_id']}: {log['action']} {log['status']}",
                    'display_id': log['display_id'],
                    'action': log['action'],
                    'timestamp': log['timestamp'],
                    'details': log['details']
                })
        
        return jsonify({
            'success': True,
            'alerts': alerts,
            'total_count': len(alerts),
            'filter': {
                'level': level_filter,
                'hours_back': hours_back
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# CONFIGURATION ENDPOINTS
# ============================================================================

@app.route('/api/config', methods=['GET'])
def get_configuration():
    """Get current system configuration"""
    try:
        return jsonify({
            'success': True,
            'config': config.config,
            'display_count': len(display_controllers),
            'model_info': {
                'model': 'LH55BECHLGFXGO',
                'series': 'Samsung BEC Series',
                'specifications': asdict(LH55BECHLGFXGOSpecs())
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/config', methods=['PUT'])
def update_configuration():
    """Update system configuration"""
    try:
        new_config = request.get_json()
        
        # Validate configuration
        validation_result = validate_config(new_config)
        if not validation_result['valid']:
            return jsonify({
                'success': False,
                'error': 'Invalid configuration',
                'validation_errors': validation_result['errors']
            }), 400
        
        # Update configuration
        config.config.update(new_config)
        config.save_config()
        
        # Reinitialize displays if display config changed
        if 'displays' in new_config:
            initialize_displays()
        
        return jsonify({
            'success': True,
            'message': 'Configuration updated successfully',
            'display_count': len(display_controllers)
        })
        
    except Exception as e:
        logger.error(f"Failed to update configuration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def validate_config(config_data):
    """Validate configuration data"""
    errors = []
    
    # Validate displays section
    if 'displays' in config_data:
        displays = config_data['displays']
        if not isinstance(displays, dict):
            errors.append('Displays must be a dictionary')
        else:
            for display_id, display_config in displays.items():
                if not isinstance(display_config, dict):
                    errors.append(f'Display {display_id} config must be a dictionary')
                    continue
                
                if 'ip' not in display_config:
                    errors.append(f'Display {display_id} missing IP address')
                
                # Validate IP format
                ip = display_config.get('ip', '')
                if not validate_ip_format(ip):
                    errors.append(f'Display {display_id} has invalid IP: {ip}')
    
    return {'valid': len(errors) == 0, 'errors': errors}

def validate_ip_format(ip):
    """Validate IP address format"""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False

# ============================================================================
# WEBSOCKET EVENTS
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected to Samsung LH55BECHLGFXGO control system')
    emit('connected', {
        'message': 'Connected to Samsung LH55BECHLGFXGO Video Wall Control System',
        'model': 'LH55BECHLGFXGO',
        'display_count': len(display_controllers)
    })

@socketio.on('subscribe_display_updates')
def handle_display_subscription(data):
    """Handle subscription to display updates"""
    display_id = data.get('display_id')
    
    if display_id and display_id in display_controllers:
        # Send current status
        controller = display_controllers[display_id]
        emit('display_status', {
            'display_id': display_id,
            'status': controller.status.to_dict()
        })
    else:
        # Send all display statuses
        all_statuses = {}
        for did, controller in display_controllers.items():
            all_statuses[did] = controller.status.to_dict()
        
        emit('all_display_status', all_statuses)

@socketio.on('request_system_health')
def handle_health_request():
    """Handle real-time health check request"""
    async def send_health():
        try:
            # This would need to be called from an async context
            # For now, send cached status
            statuses = {}
            for display_id, controller in display_controllers.items():
                statuses[display_id] = controller.status.to_dict()
            
            emit('system_health_update', {
                'timestamp': datetime.now().isoformat(),
                'display_statuses': statuses
            })
        except Exception as e:
            emit('error', {'message': str(e)})
    
    # In a real implementation, you'd run this with asyncio
    # For now, just send current cached statuses
    statuses = {}
    for display_id, controller in display_controllers.items():
        statuses[display_id] = controller.status.to_dict()
    
    emit('system_health_update', {
        'timestamp': datetime.now().isoformat(),
        'display_statuses': statuses
    })

# Add to main application initialization
def initialize_api():
    """Initialize API components"""
    logger.info("Samsung LH55BECHLGFXGO API endpoints initialized")
    logger.info(f"Supporting {len(display_controllers)} displays")
    logger.info("Video wall support: Up to 10x10 grid")
    logger.info("MDC protocol: Enabled")

# Call this after your main app setup
if __name__ == "__main__":
    initialize_api()