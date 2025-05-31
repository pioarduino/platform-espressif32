# component_manager.py
import os
import shutil
import re
import yaml
from yaml import SafeLoader
from os.path import join
from typing import Set, Optional, Dict, Any, List, Tuple


class ComponentManager:
    """Manages IDF components for ESP32 Arduino framework builds with logging support."""
    
    def __init__(self, env):
        """
        Initialize the ComponentManager.
        
        Args:
            env: PlatformIO environment object
        """
        self.env = env
        self.platform = env.PioPlatform()
        self.config = env.GetProjectConfig()
        self.board = env.BoardConfig()
        self.mcu = self.board.get("build.mcu", "esp32").lower()
        self.project_src_dir = env.subst("$PROJECT_SRC_DIR")
        self.removed_components: Set[str] = set()
        self.ignored_libs: Set[str] = set()
        
        # Simple logging attributes
        self.component_changes: List[str] = []
        
        self.arduino_framework_dir = self.platform.get_package_dir("framework-arduinoespressif32")
        self.arduino_libs_mcu = join(self.platform.get_package_dir("framework-arduinoespressif32-libs"), self.mcu)
    
    def _log_change(self, message: str) -> None:
        """
        Simple logging without timestamp.
        
        Args:
            message: Log message to record
        """
        self.component_changes.append(message)
        print(f"[ComponentManager] {message}")
    
    def handle_component_settings(self, add_components: bool = False, remove_components: bool = False) -> None:
        """
        Handle adding and removing IDF components based on project configuration.
        
        Args:
            add_components: Whether to process component additions
            remove_components: Whether to process component removals
        """

        # Create backup before first component removal and on every add of a component
        if remove_components and not self.removed_components or add_components:
            self._backup_pioarduino_build_py()
            self._log_change("Created backup of build file")
    
        # Check if env and GetProjectOption are available
        if hasattr(self, 'env') and hasattr(self.env, 'GetProjectOption'):
            component_yml_path = self._get_or_create_component_yml()
            component_data = self._load_component_yml(component_yml_path)
    
            if remove_components:
                try:
                    remove_option = self.env.GetProjectOption("custom_component_remove", None)
                    if remove_option:
                        components_to_remove = remove_option.splitlines()
                        self._remove_components(component_data, components_to_remove)
                except Exception as e:
                    self._log_change(f"Error removing components: {str(e)}")
    
            if add_components:
                try:
                    add_option = self.env.GetProjectOption("custom_component_add", None)
                    if add_option:
                        components_to_add = add_option.splitlines()
                        self._add_components(component_data, components_to_add)
                except Exception as e:
                    self._log_change(f"Error adding components: {str(e)}")

            self._save_component_yml(component_yml_path, component_data)
        
            # Clean up removed components
            if self.removed_components:
                self._cleanup_removed_components()

        self.handle_lib_ignore()
        
        # Print summary
        if self.component_changes:
            self._log_change(f"Session completed with {len(self.component_changes)} changes")
    
    def handle_lib_ignore(self) -> None:
        """Handle lib_ignore entries from platformio.ini and remove corresponding includes."""
        # Create backup before processing lib_ignore
        if not self.ignored_libs:
            self._backup_pioarduino_build_py()
        
        # Get lib_ignore entries from current environment only
        lib_ignore_entries = self._get_lib_ignore_entries()
        
        if lib_ignore_entries:
            self.ignored_libs.update(lib_ignore_entries)
            self._remove_ignored_lib_includes()
            self._log_change(f"Processed {len(lib_ignore_entries)} ignored libraries")
    
    def _get_lib_ignore_entries(self) -> List[str]:
        """
        Get lib_ignore entries from current environment configuration only.
        
        Returns:
            List of library names to ignore
        """
        try:
            # Get lib_ignore from current environment only
            lib_ignore = self.env.GetProjectOption("lib_ignore", [])
            
            if isinstance(lib_ignore, str):
                lib_ignore = [lib_ignore]
            elif lib_ignore is None:
                lib_ignore = []
            
            # Clean and normalize entries
            cleaned_entries = []
            for entry in lib_ignore:
                entry = str(entry).strip()
                if entry:
                    # Convert library names to potential include directory names
                    include_name = self._convert_lib_name_to_include(entry)
                    cleaned_entries.append(include_name)
            
            # Filter out critical ESP32 components that should never be ignored
            critical_components = [
                'lwip',           # Network stack
                'freertos',       # Real-time OS
                'esp_system',     # System functions
                'esp_common',     # Common ESP functions
                'driver',         # Hardware drivers
                'nvs_flash',      # Non-volatile storage
                'spi_flash',      # Flash memory access
                'esp_timer',      # Timer functions
                'esp_event',      # Event system
                'log'             # Logging system
            ]
            
            filtered_entries = []
            for entry in cleaned_entries:
                if entry not in critical_components:
                    filtered_entries.append(entry)
            
            return filtered_entries
            
        except Exception:
            return []
    
    def _has_bt_ble_dependencies(self) -> bool:
        """
        Check if lib_deps contains any BT/BLE related dependencies.
        
        Returns:
            True if BT/BLE dependencies are found
        """
        try:
            # Get lib_deps from current environment
            lib_deps = self.env.GetProjectOption("lib_deps", [])
            
            if isinstance(lib_deps, str):
                lib_deps = [lib_deps]
            elif lib_deps is None:
                lib_deps = []
            
            # Convert to string and check for BT/BLE keywords
            lib_deps_str = ' '.join(str(dep) for dep in lib_deps).upper()
            
            bt_ble_keywords = ['BLE', 'BT', 'NIMBLE', 'BLUETOOTH']

            return any(keyword in lib_deps_str for keyword in bt_ble_keywords)
            
        except Exception:
            return False
    
    def _is_bt_related_library(self, lib_name: str) -> bool:
        """
        Check if a library name is related to Bluetooth/BLE functionality.
        
        Args:
            lib_name: Library name to check
            
        Returns:
            True if library is BT/BLE related
        """
        lib_name_upper = lib_name.upper()
        
        bt_related_names = [
            'BT',
            'BLE', 
            'BLUETOOTH',
            'NIMBLE',
            'ESP32_BLE',
            'ESP32BLE',
            'BLUETOOTHSERIAL',
            'BLE_ARDUINO',
            'ESP_BLE',
            'ESP_BT'
        ]

        return any(bt_name in lib_name_upper for bt_name in bt_related_names)
    
    def _get_arduino_core_libraries(self) -> Dict[str, str]:
        """
        Get all Arduino core libraries and their corresponding include paths.
        
        Returns:
            Dictionary mapping library names to include paths
        """
        libraries_mapping = {}
        
        # Path to Arduino Core Libraries
        arduino_libs_dir = join(self.arduino_framework_dir, "libraries")
        
        if not os.path.exists(arduino_libs_dir):
            return libraries_mapping
        
        try:
            for entry in os.listdir(arduino_libs_dir):
                lib_path = join(arduino_libs_dir, entry)
                if os.path.isdir(lib_path):
                    lib_name = self._get_library_name_from_properties(lib_path)
                    if lib_name:
                        include_path = self._map_library_to_include_path(lib_name, entry)
                        libraries_mapping[lib_name.lower()] = include_path
                        libraries_mapping[entry.lower()] = include_path  # Also use directory name as key
        except Exception:
            pass
        
        return libraries_mapping
    
    def _get_library_name_from_properties(self, lib_dir: str) -> Optional[str]:
        """
        Extract library name from library.properties file.
        
        Args:
            lib_dir: Library directory path
            
        Returns:
            Library name or None if not found
        """
        prop_path = join(lib_dir, "library.properties")
        if not os.path.isfile(prop_path):
            return None
        
        try:
            with open(prop_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('name='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
        
        return None
    
    def _map_library_to_include_path(self, lib_name: str, dir_name: str) -> str:
        """
        Map library name to corresponding include path.
        
        Args:
            lib_name: Library name
            dir_name: Directory name
            
        Returns:
            Mapped include path
        """
        lib_name_lower = lib_name.lower().replace(' ', '').replace('-', '_')
        dir_name_lower = dir_name.lower()
        
        # Extended mapping list with Arduino Core Libraries
        extended_mapping = {
            # Core ESP32 mappings
            'wifi': 'esp_wifi',
            'bluetooth': 'bt',
            'bluetoothserial': 'bt',
            'ble': 'bt',
            'bt': 'bt',
            'ethernet': 'esp_eth',
            'websocket': 'esp_websocket_client',
            'http': 'esp_http_client',
            'https': 'esp_https_ota',
            'ota': 'esp_https_ota',
            'spiffs': 'spiffs',
            'fatfs': 'fatfs',
            'mesh': 'esp_wifi_mesh',
            'smartconfig': 'esp_smartconfig',
            'mdns': 'mdns',
            'coap': 'coap',
            'mqtt': 'mqtt',
            'json': 'cjson',
            'mbedtls': 'mbedtls',
            'openssl': 'openssl',
            
            # Arduino Core specific mappings (safe mappings that don't conflict with critical components)
            'esp32blearduino': 'bt',
            'esp32_ble_arduino': 'bt',
            'esp32': 'esp32',
            'wire': 'driver',
            'spi': 'driver',
            'i2c': 'driver',
            'uart': 'driver',
            'serial': 'driver',
            'analogwrite': 'driver',
            'ledc': 'driver',
            'pwm': 'driver',
            'dac': 'driver',
            'adc': 'driver',
            'touch': 'driver',
            'hall': 'driver',
            'rtc': 'driver',
            'timer': 'esp_timer',
            'preferences': 'arduino_preferences',
            'eeprom': 'arduino_eeprom',
            'update': 'esp_https_ota',
            'httpupdate': 'esp_https_ota',
            'httpclient': 'esp_http_client',
            'httpsclient': 'esp_https_ota',
            'wifimanager': 'esp_wifi',
            'wificlientsecure': 'esp_wifi',
            'wifiserver': 'esp_wifi',
            'wifiudp': 'esp_wifi',
            'wificlient': 'esp_wifi',
            'wifiap': 'esp_wifi',
            'wifimulti': 'esp_wifi',
            'esp32webserver': 'esp_http_server',
            'webserver': 'esp_http_server',
            'asyncwebserver': 'esp_http_server',
            'dnsserver': 'lwip',
            'netbios': 'netbios',
            'simpletime': 'lwip',
            'fs': 'vfs',
            'sd': 'fatfs',
            'sd_mmc': 'fatfs',
            'littlefs': 'esp_littlefs',
            'ffat': 'fatfs',
            'camera': 'esp32_camera',
            'esp_camera': 'esp32_camera',
            'arducam': 'esp32_camera',
            'rainmaker': 'esp_rainmaker',
            'esp_rainmaker': 'esp_rainmaker',
            'provisioning': 'wifi_provisioning',
            'wifiprovisioning': 'wifi_provisioning',
            'espnow': 'esp_now',
            'esp_now': 'esp_now',
            'esptouch': 'esp_smartconfig',
            'ping': 'lwip',
            'netif': 'lwip',
            'tcpip': 'lwip'
        }
        
        # Check extended mapping first
        if lib_name_lower in extended_mapping:
            return extended_mapping[lib_name_lower]
        
        # Check directory name
        if dir_name_lower in extended_mapping:
            return extended_mapping[dir_name_lower]
        
        # Fallback: Use directory name as include path
        return dir_name_lower
    
    def _convert_lib_name_to_include(self, lib_name: str) -> str:
        """
        Convert library name to potential include directory name.
        
        Args:
            lib_name: Library name to convert
            
        Returns:
            Converted include directory name
        """
        # Load Arduino Core Libraries on first call
        if not hasattr(self, '_arduino_libraries_cache'):
            self._arduino_libraries_cache = self._get_arduino_core_libraries()
        
        lib_name_lower = lib_name.lower()
        
        # Check Arduino Core Libraries first
        if lib_name_lower in self._arduino_libraries_cache:
            return self._arduino_libraries_cache[lib_name_lower]
        
        # Remove common prefixes and suffixes
        cleaned_name = lib_name_lower
        
        # Remove common prefixes
        prefixes_to_remove = ['lib', 'arduino-', 'esp32-', 'esp-']
        for prefix in prefixes_to_remove:
            if cleaned_name.startswith(prefix):
                cleaned_name = cleaned_name[len(prefix):]
        
        # Remove common suffixes
        suffixes_to_remove = ['-lib', '-library', '.h']
        for suffix in suffixes_to_remove:
            if cleaned_name.endswith(suffix):
                cleaned_name = cleaned_name[:-len(suffix)]
        
        # Check again with cleaned name
        if cleaned_name in self._arduino_libraries_cache:
            return self._arduino_libraries_cache[cleaned_name]
        
        # Direct mapping for common cases not in Arduino libraries
        direct_mapping = {
            'ble': 'bt',
            'bluetooth': 'bt',
            'bluetoothserial': 'bt'
        }
        
        if cleaned_name in direct_mapping:
            return direct_mapping[cleaned_name]
        
        return cleaned_name
    
    def _remove_ignored_lib_includes(self) -> None:
        """Remove include entries for ignored libraries from pioarduino-build.py with simple logging."""
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        
        if not os.path.exists(build_py_path):
            self._log_change("Build file not found")
            return
        
        # Check if BT/BLE dependencies exist in lib_deps
        bt_ble_protected = self._has_bt_ble_dependencies()
        if bt_ble_protected:
            self._log_change("BT/BLE protection enabled")
        
        try:
            with open(build_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            total_removed = 0
            
            # Remove CPPPATH entries for each ignored library
            for lib_name in self.ignored_libs:
                # Skip BT-related libraries if BT/BLE dependencies are present
                if bt_ble_protected and self._is_bt_related_library(lib_name):
                    self._log_change(f"Protected BT library: {lib_name}")
                    continue
                
                # Hard protection for DSP components
                if lib_name.lower() in ['dsp', 'esp_dsp', 'dsps', 'fft2r', 'dsps_fft2r']:
                    self._log_change(f"Protected DSP component: {lib_name}")
                    continue
                    
                # Multiple patterns to catch different include formats
                patterns = [
                    rf'.*join\([^,]*,\s*"include",\s*"{re.escape(lib_name)}"[^)]*\),?\n',
                    rf'.*"include/{re.escape(lib_name)}"[^,\n]*,?\n',
                    rf'.*"[^"]*include[^"]*{re.escape(lib_name)}[^"]*"[^,\n]*,?\n',
                    rf'.*"[^"]*/{re.escape(lib_name)}/include[^"]*"[^,\n]*,?\n',
                    rf'.*"[^"]*{re.escape(lib_name)}[^"]*include[^"]*"[^,\n]*,?\n',
                    rf'.*join\([^)]*"include"[^)]*"{re.escape(lib_name)}"[^)]*\),?\n',
                    rf'.*"{re.escape(lib_name)}/include"[^,\n]*,?\n',
                    rf'\s*"[^"]*/{re.escape(lib_name)}/[^"]*",?\n'
                ]
                
                removed_count = 0
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        content = re.sub(pattern, '', content)
                        removed_count += len(matches)
                
                if removed_count > 0:
                    self._log_change(f"Ignored library: {lib_name} ({removed_count} entries)")
                    total_removed += removed_count
            
            # Clean up empty lines and trailing commas
            content = re.sub(r'\n\s*\n', '\n', content)
            content = re.sub(r',\s*\n\s*\]', '\n]', content)
            
            # Validate and write changes
            if self._validate_changes(original_content, content) and content != original_content:
                with open(build_py_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self._log_change(f"Updated build file ({total_removed} total removals)")
                
        except (IOError, OSError) as e:
            self._log_change(f"Error processing libraries: {str(e)}")
        except Exception as e:
            self._log_change(f"Unexpected error processing libraries: {str(e)}")
    
    def _validate_changes(self, original_content: str, new_content: str) -> bool:
        """
        Validate that the changes are reasonable.
        
        Args:
            original_content: Original file content
            new_content: Modified file content
            
        Returns:
            True if changes are valid
        """
        original_lines = len(original_content.splitlines())
        new_lines = len(new_content.splitlines())
        removed_lines = original_lines - new_lines
        
        # Don't allow removing more than 50% of the file or negative changes
        return not (removed_lines > original_lines * 0.5 or removed_lines < 0)
    
    def _get_or_create_component_yml(self) -> str:
        """
        Get path to idf_component.yml, creating it if necessary.
        
        Returns:
            Path to component YAML file
        """
        # Try Arduino framework first
        framework_yml = join(self.arduino_framework_dir, "idf_component.yml")
        if os.path.exists(framework_yml):
            self._create_backup(framework_yml)
            return framework_yml
        
        # Try project source directory
        project_yml = join(self.project_src_dir, "idf_component.yml")
        if os.path.exists(project_yml):
            self._create_backup(project_yml)
            return project_yml
        
        # Create new file in project source
        self._create_default_component_yml(project_yml)
        return project_yml
    
    def _create_backup(self, file_path: str) -> None:
        """
        Create backup of a file.
        
        Args:
            file_path: Path to file to backup
        """
        backup_path = f"{file_path}.orig"
        if not os.path.exists(backup_path):
            shutil.copy(file_path, backup_path)
    
    def _create_default_component_yml(self, file_path: str) -> None:
        """
        Create a default idf_component.yml file.
        
        Args:
            file_path: Path where to create the file
        """
        default_content = {
            "dependencies": {
                "idf": ">=5.1"
            }
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_content, f)
    
    def _load_component_yml(self, file_path: str) -> Dict[str, Any]:
        """
        Load and parse idf_component.yml file.
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            Parsed YAML data
        """
        try:
            with open(file_path, "r", encoding='utf-8') as f:
                return yaml.load(f, Loader=SafeLoader) or {"dependencies": {}}
        except Exception:
            return {"dependencies": {}}
    
    def _save_component_yml(self, file_path: str, data: Dict[str, Any]) -> None:
        """
        Save component data to YAML file.
        
        Args:
            file_path: Path to YAML file
            data: Data to save
        """
        try:
            with open(file_path, "w", encoding='utf-8') as f:
                yaml.dump(data, f)
        except Exception:
            pass
    
    def _remove_components(self, component_data: Dict[str, Any], components_to_remove: list) -> None:
        """
        Remove specified components from the configuration with simple logging.
        
        Args:
            component_data: Component configuration data
            components_to_remove: List of components to remove
        """
        dependencies = component_data.setdefault("dependencies", {})
        
        for component in components_to_remove:
            component = component.strip()
            if not component:
                continue
                
            if component in dependencies:
                self._log_change(f"Removed component: {component}")
                del dependencies[component]
                
                # Track for cleanup
                filesystem_name = self._convert_component_name_to_filesystem(component)
                self.removed_components.add(filesystem_name)
            else:
                self._log_change(f"Component not found: {component}")
    
    def _add_components(self, component_data: Dict[str, Any], components_to_add: list) -> None:
        """
        Add specified components to the configuration with simple logging.
        
        Args:
            component_data: Component configuration data
            components_to_add: List of components to add
        """
        dependencies = component_data.setdefault("dependencies", {})
        
        for component in components_to_add:
            component = component.strip()
            if len(component) <= 4:  # Skip too short entries
                continue
            
            component_name, version = self._parse_component_entry(component)
            
            if component_name not in dependencies:
                dependencies[component_name] = {"version": version}
                self._log_change(f"Added component: {component_name} ({version})")
            else:
                self._log_change(f"Component already exists: {component_name}")
    
    def _parse_component_entry(self, entry: str) -> Tuple[str, str]:
        """
        Parse component entry into name and version.
        
        Args:
            entry: Component entry string
            
        Returns:
            Tuple of (component_name, version)
        """
        if "@" in entry:
            name, version = entry.split("@", 1)
            return (name.strip(), version.strip())
        return (entry.strip(), "*")
    
    def _convert_component_name_to_filesystem(self, component_name: str) -> str:
        """
        Convert component name from registry format to filesystem format.
        
        Args:
            component_name: Component name to convert
            
        Returns:
            Filesystem-safe component name
        """
        return component_name.replace("/", "__")
    
    def _backup_pioarduino_build_py(self) -> None:
        """Create backup of the original pioarduino-build.py."""
        if "arduino" not in self.env.subst("$PIOFRAMEWORK"):
            return
        
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        backup_path = join(self.arduino_libs_mcu, f"pioarduino-build.py.{self.mcu}")
        
        if os.path.exists(build_py_path) and not os.path.exists(backup_path):
            shutil.copy2(build_py_path, backup_path)
    
    def _cleanup_removed_components(self) -> None:
        """Clean up removed components and restore original build file."""
        for component in self.removed_components:
            self._remove_include_directory(component)
        
        self._remove_cpppath_entries()
    
    def _remove_include_directory(self, component: str) -> None:
        """
        Remove include directory for a component.
        
        Args:
            component: Component name
        """
        include_path = join(self.arduino_libs_mcu, "include", component)
        
        if os.path.exists(include_path):
            shutil.rmtree(include_path)
    
    def _remove_cpppath_entries(self) -> None:
        """Remove CPPPATH entries for removed components from pioarduino-build.py."""
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        
        if not os.path.exists(build_py_path):
            return
        
        try:
            with open(build_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Remove CPPPATH entries for each removed component
            for component in self.removed_components:
                patterns = [
                    rf'.*join\([^,]*,\s*"include",\s*"{re.escape(component)}"[^)]*\),?\n',
                    rf'.*"include/{re.escape(component)}"[^,\n]*,?\n',
                    rf'.*"[^"]*include[^"]*{re.escape(component)}[^"]*"[^,\n]*,?\n'
                ]
                
                for pattern in patterns:
                    content = re.sub(pattern, '', content)
            
            if content != original_content:
                with open(build_py_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
        except Exception:
            pass
    
    def restore_pioarduino_build_py(self, target=None, source=None, env=None) -> None:
        """
        Restore the original pioarduino-build.py from backup.
        
        Args:
            target: Build target (unused)
            source: Build source (unused)
            env: Environment (unused)
        """
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        backup_path = join(self.arduino_libs_mcu, f"pioarduino-build.py.{self.mcu}")
        
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, build_py_path)
            os.remove(backup_path)
    
    def get_changes_summary(self) -> List[str]:
        """
        Get simple list of all changes made.
        
        Returns:
            List of change messages
        """
        return self.component_changes.copy()

    def print_changes_summary(self) -> None:
        """Print a simple summary of all changes."""
        if self.component_changes:
            print("\n=== Component Manager Changes ===")
            for change in self.component_changes:
                print(f"  {change}")
            print("=" * 35)
        else:
            print("[ComponentManager] No changes made")
