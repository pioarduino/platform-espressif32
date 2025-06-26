# component_manager.py
"""
ESP32 Arduino Framework Component Manager

This module provides a comprehensive system for managing IDF components in ESP32 Arduino
framework builds. It handles component addition/removal, library mapping, project analysis,
and build file management with extensive logging support.

Classes:
    ComponentLogger: Handles logging functionality for component operations
    ComponentYamlHandler: Manages YAML file operations for component configuration
    ProjectAnalyzer: Analyzes project dependencies and component usage
    LibraryMapper: Maps library names to include paths
    BuildFileManager: Manages backup and restoration of build files
    ComponentManager: Main manager class that coordinates all component operations

Author: Jason2866 ESP32 pioarduino Framework maintainer
License: Apache 2.0
"""

import os
import shutil
import re
import yaml
from yaml import SafeLoader
from os.path import join
from typing import Set, Optional, Dict, Any, List


class ComponentLogger:
    """
    Handles logging functionality for component operations.
    
    This class provides a centralized logging mechanism for tracking all component
    management operations, including changes, errors, and status updates.
    
    Attributes:
        component_changes (List[str]): List of all logged change messages
        
    Example:
        >>> logger = ComponentLogger()
        >>> logger.log_change("Component added successfully")
        >>> print(logger.get_change_count())
        1
    """
    
    def __init__(self):
        """
        Initialize the logger with an empty change list.
        
        Creates a new ComponentLogger instance with an empty list to track
        all component-related changes during the session.
        """
        self.component_changes: List[str] = []
    
    def log_change(self, message: str) -> None:
        """
        Log a component change with simple console output.
        
        Records a change message both in the internal list and outputs it
        to the console with a standardized format.
        
        Args:
            message (str): The message to log describing the change
            
        Example:
            >>> logger = ComponentLogger()
            >>> logger.log_change("Added WiFi component")
            [ComponentManager] Added WiFi component
        """
        self.component_changes.append(message)
        print(f"[ComponentManager] {message}")
    
    def get_changes(self) -> List[str]:
        """
        Get all logged changes.
        
        Returns a copy of all change messages that have been logged during
        the current session.
        
        Returns:
            List[str]: List of all logged change messages
            
        Example:
            >>> logger = ComponentLogger()
            >>> logger.log_change("First change")
            >>> logger.log_change("Second change")
            >>> changes = logger.get_changes()
            >>> len(changes)
            2
        """
        return self.component_changes
    
    def get_change_count(self) -> int:
        """
        Get the number of changes logged.
        
        Returns the total count of changes that have been logged during
        the current session.
        
        Returns:
            int: Number of logged changes
            
        Example:
            >>> logger = ComponentLogger()
            >>> logger.log_change("Change 1")
            >>> logger.get_change_count()
            1
        """
        return len(self.component_changes)


class ComponentYamlHandler:
    """
    Handles YAML file operations for component configuration.
    
    This class manages all operations related to the idf_component.yml file,
    including creation, loading, saving, and backup operations. It provides
    a clean interface for component configuration management.
    
    Attributes:
        logger (ComponentLogger): Logger instance for recording operations
        
    Example:
        >>> logger = ComponentLogger()
        >>> handler = ComponentYamlHandler(logger)
        >>> data = handler.load_component_yml("path/to/component.yml")
    """
    
    def __init__(self, logger: ComponentLogger):
        """
        Initialize the YAML handler.
        
        Creates a new ComponentYamlHandler with a reference to a logger
        for recording all YAML-related operations.
        
        Args:
            logger (ComponentLogger): Logger instance for recording operations
        """
        self.logger = logger
    
    def get_or_create_component_yml(self, arduino_framework_dir: str, project_src_dir: str) -> str:
        """
        Get path to idf_component.yml, creating it if necessary.
        
        Searches for an existing idf_component.yml file in the Arduino framework
        directory first, then in the project source directory. If neither exists,
        creates a new default file in the project source directory.
        
        Args:
            arduino_framework_dir (str): Path to Arduino framework directory
            project_src_dir (str): Path to project source directory
            
        Returns:
            str: Path to the component YAML file
            
        Example:
            >>> handler = ComponentYamlHandler(logger)
            >>> yml_path = handler.get_or_create_component_yml("/framework", "/project/src")
            >>> os.path.exists(yml_path)
            True
        """
        # Try Arduino framework first
        framework_yml = join(arduino_framework_dir, "idf_component.yml")
        if os.path.exists(framework_yml):
            self._create_backup(framework_yml)
            return framework_yml
        
        # Try project source directory
        project_yml = join(project_src_dir, "idf_component.yml")
        if os.path.exists(project_yml):
            self._create_backup(project_yml)
            return project_yml
        
        # Create new file in project source
        self._create_default_component_yml(project_yml)
        self.logger.log_change(f"Created new component.yml file at {project_yml}")
        return project_yml
    
    def load_component_yml(self, file_path: str) -> Dict[str, Any]:
        """
        Load and parse idf_component.yml file.
        
        Attempts to load and parse a YAML file containing component configuration.
        If the file doesn't exist or cannot be parsed, returns a default structure
        with an empty dependencies section.
        
        Args:
            file_path (str): Path to the YAML file to load
            
        Returns:
            Dict[str, Any]: Parsed YAML data as dictionary with at least a 'dependencies' key
            
        Example:
            >>> handler = ComponentYamlHandler(logger)
            >>> data = handler.load_component_yml("component.yml")
            >>> 'dependencies' in data
            True
        """
        try:
            with open(file_path, "r") as f:
                return yaml.load(f, Loader=SafeLoader) or {"dependencies": {}}
        except Exception:
            return {"dependencies": {}}
    
    def save_component_yml(self, file_path: str, data: Dict[str, Any]) -> None:
        """
        Save component data to YAML file.
        
        Writes component configuration data to a YAML file with proper formatting.
        Logs the operation result, including any errors that occur during saving.
        
        Args:
            file_path (str): Path where to save the YAML file
            data (Dict[str, Any]): Component data to save
            
        Example:
            >>> handler = ComponentYamlHandler(logger)
            >>> data = {"dependencies": {"esp_wifi": {"version": "*"}}}
            >>> handler.save_component_yml("component.yml", data)
        """
        try:
            with open(file_path, "w") as f:
                yaml.dump(data, f)
            self.logger.log_change(f"Saved component configuration to {file_path}")
        except Exception as e:
            self.logger.log_change(f"Error saving component configuration: {str(e)}")
    
    def _create_backup(self, file_path: str) -> None:
        """
        Create backup of a file.
        
        Creates a backup copy of the specified file by appending '.orig' to the filename.
        Only creates the backup if it doesn't already exist to preserve the original.
        
        Args:
            file_path (str): Path to the file to backup
            
        Example:
            >>> handler._create_backup("component.yml")
            # Creates component.yml.orig if it doesn't exist
        """
        backup_path = f"{file_path}.orig"
        if not os.path.exists(backup_path):
            shutil.copy(file_path, backup_path)
            self.logger.log_change(f"Created backup: {backup_path}")
    
    def _create_default_component_yml(self, file_path: str) -> None:
        """
        Create a default idf_component.yml file.
        
        Creates a new component YAML file with minimal default configuration
        that includes only the IDF version requirement.
        
        Args:
            file_path (str): Path where to create the default file
            
        Example:
            >>> handler._create_default_component_yml("new_component.yml")
            # Creates file with default IDF dependency
        """
        default_content = {
            "dependencies": {
                "idf": ">=5.1"
            }
        }
        
        with open(file_path, 'w') as f:
            yaml.dump(default_content, f)


class ProjectAnalyzer:
    """
    Analyzes project dependencies and component usage.
    
    This class provides functionality to analyze project source files and
    configuration to determine which ESP-IDF components are actually being
    used. This helps prevent removal of critical components and optimizes
    the build process.
    
    Attributes:
        env: PlatformIO environment object
        _project_components_cache (Optional[Set[str]]): Cached analysis results
        
    Example:
        >>> analyzer = ProjectAnalyzer(env)
        >>> used_components = analyzer.analyze_project_dependencies()
        >>> analyzer.is_component_used_in_project("esp_wifi")
        True
    """
    
    def __init__(self, env):
        """
        Initialize the project analyzer.
        
        Creates a new ProjectAnalyzer with a reference to the PlatformIO
        environment for accessing project configuration and files.
        
        Args:
            env: PlatformIO environment object containing project information
        """
        self.env = env
        self._project_components_cache = None
    
    def analyze_project_dependencies(self) -> Set[str]:
        """
        Analyze project files to detect actually used components/libraries.
        
        Performs a comprehensive analysis of project source files and library
        dependencies to identify which ESP-IDF components are actually being
        used in the project. This includes parsing source code for includes
        and function calls, as well as analyzing lib_deps entries.
        
        Returns:
            Set[str]: Set of component names that are used in the project
            
        Example:
            >>> analyzer = ProjectAnalyzer(env)
            >>> components = analyzer.analyze_project_dependencies()
            >>> "esp_wifi" in components  # If project uses WiFi
            True
        """
        used_components = set()
        
        try:
            # Analyze project source files
            src_dir = self.env.subst("$PROJECT_SRC_DIR")
            if os.path.exists(src_dir):
                for root, dirs, files in os.walk(src_dir):
                    for file in files:
                        if file.endswith(('.cpp', '.c', '.h', '.hpp', '.ino')):
                            file_path = os.path.join(root, file)
                            used_components.update(self._extract_components_from_file(file_path))
            
            # Analyze lib_deps for explicit dependencies (if present)
            lib_deps = self.env.GetProjectOption("lib_deps", [])
            if isinstance(lib_deps, str):
                lib_deps = [lib_deps]
            
            for dep in lib_deps:
                used_components.update(self._extract_components_from_lib_dep(str(dep)))
                
        except Exception:
            pass
        
        return used_components
    
    def is_component_used_in_project(self, lib_name: str) -> bool:
        """
        Check if a component/library is actually used in the project.
        
        Determines whether a specific component or library is being used in the
        project by checking against the cached analysis results. Uses both direct
        matching and partial matching for related components.
        
        Args:
            lib_name (str): Name of the library/component to check
            
        Returns:
            bool: True if the component is used in the project, False otherwise
            
        Example:
            >>> analyzer = ProjectAnalyzer(env)
            >>> analyzer.is_component_used_in_project("esp_wifi")
            True  # If WiFi functionality is detected in project
        """
        # Cache project analysis for performance
        if self._project_components_cache is None:
            self._project_components_cache = self.analyze_project_dependencies()
        
        lib_name_lower = lib_name.lower()
        
        # Direct match
        if lib_name_lower in self._project_components_cache:
            return True
        
        # Partial match for related components
        for used_component in self._project_components_cache:
            if lib_name_lower in used_component or used_component in lib_name_lower:
                return True
        
        return False
    
    def _extract_components_from_file(self, file_path: str) -> Set[str]:
        """
        Extract component usage from a single file by analyzing includes and function calls.
        
        Analyzes a source file to detect which ESP-IDF components are being used
        by looking for specific patterns in the code such as include statements,
        function calls, and API usage patterns.
        
        Args:
            file_path (str): Path to the source file to analyze
            
        Returns:
            Set[str]: Set of component names found in the file
            
        Example:
            >>> analyzer = ProjectAnalyzer(env)
            >>> components = analyzer._extract_components_from_file("main.cpp")
            >>> "esp_wifi" in components  # If file contains WiFi code
            True
        """
        components = set()
        
        # Component detection patterns - maps component names to code patterns
        component_patterns = {
            'bt': ['bluetooth', 'ble', 'nimble', 'bt_', 'esp_bt', 'esp_ble'],
            'esp_wifi': ['wifi', 'esp_wifi', 'tcpip_adapter'],
            'esp_dsp': ['dsps_', 'esp_dsp', 'fft2r', 'dsps_fft2r'],  # Enhanced DSP detection
            'esp_http_client': ['esp_http_client', 'http_client'],
            'esp_https_ota': ['esp_https_ota', 'esp_ota'],
            'mdns': ['mdns', 'esp_mdns'],
            'mqtt': ['mqtt', 'esp_mqtt'],
            'spiffs': ['spiffs', 'esp_spiffs'],
            'fatfs': ['fatfs', 'ff.h'],
            'nvs_flash': ['nvs', 'nvs_flash'],
            'esp_timer': ['esp_timer', 'timer_'],
            'driver': ['gpio_', 'uart_', 'spi_', 'i2c_', 'adc_', 'dac_'],
            'esp_camera': ['esp_camera', 'camera.h'],
            'esp_now': ['esp_now', 'espnow'],
            'esp_smartconfig': ['smartconfig', 'esp_smartconfig'],
            'esp_eth': ['esp_eth', 'ethernet'],
            'esp_websocket_client': ['websocket', 'esp_websocket'],
            'cjson': ['cjson', 'json'],
            'mbedtls': ['mbedtls', 'ssl'],
            'openssl': ['openssl']
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().lower()
                
                for component, patterns in component_patterns.items():
                    if any(pattern in content for pattern in patterns):
                        components.add(component)
                        
        except Exception:
            pass
        
        return components
    
    def _extract_components_from_lib_dep(self, lib_dep: str) -> Set[str]:
        """
        Extract components from lib_deps entry by mapping library names to ESP-IDF components.
        
        Analyzes a library dependency string from platformio.ini and maps it to
        corresponding ESP-IDF components that would be required to support that library.
        
        Args:
            lib_dep (str): Library dependency string from platformio.ini
            
        Returns:
            Set[str]: Set of ESP-IDF component names that correspond to the library
            
        Example:
            >>> analyzer = ProjectAnalyzer(env)
            >>> components = analyzer._extract_components_from_lib_dep("WiFi")
            >>> "esp_wifi" in components
            True
        """
        components = set()
        lib_dep_upper = lib_dep.upper()
        
        # Map lib_deps entries to ESP-IDF components
        lib_dep_mapping = {
            'bt': ['BLE', 'BT', 'BLUETOOTH', 'NIMBLE'],
            'esp_wifi': ['WIFI', 'ASYNCTCP', 'ESPASYNCWEBSERVER'],
            'esp_dsp': ['DSP', 'FFT', 'JPEG'],
            'esp_http_client': ['HTTP', 'HTTPCLIENT'],
            'mqtt': ['MQTT', 'PUBSUB'],
            'esp_camera': ['CAMERA', 'ESP32CAM'],
            'esp_now': ['ESPNOW', 'ESP_NOW'],
            'mdns': ['MDNS'],
            'esp_eth': ['ETHERNET']
        }
        
        for component, keywords in lib_dep_mapping.items():
            if any(keyword in lib_dep_upper for keyword in keywords):
                components.add(component)
        
        return components


class LibraryMapper:
    """
    Handles mapping between library names and include paths.
    
    This class provides functionality to map Arduino library names to their
    corresponding ESP-IDF component include paths. It maintains a comprehensive
    mapping database and can analyze Arduino library properties to determine
    the correct include paths.
    
    Attributes:
        arduino_framework_dir (str): Path to Arduino framework directory
        _arduino_libraries_cache (Optional[Dict[str, str]]): Cached library mappings
        
    Example:
        >>> mapper = LibraryMapper("/path/to/arduino/framework")
        >>> include_path = mapper.convert_lib_name_to_include("WiFi")
        >>> include_path
        "esp_wifi"
    """
    
    def __init__(self, arduino_framework_dir: str):
        """
        Initialize the library mapper.
        
        Creates a new LibraryMapper with the path to the Arduino framework
        directory for analyzing available libraries and their properties.
        
        Args:
            arduino_framework_dir (str): Path to Arduino framework directory
        """
        self.arduino_framework_dir = arduino_framework_dir
        self._arduino_libraries_cache = None
    
    def convert_lib_name_to_include(self, lib_name: str) -> str:
        """
        Convert library name to potential include directory name.
        
        Takes an Arduino library name and converts it to the corresponding
        ESP-IDF component include path. This involves checking against known
        Arduino libraries, applying naming conventions, and using fallback
        mapping rules.
        
        Args:
            lib_name (str): Name of the library to convert
            
        Returns:
            str: Converted include directory name
            
        Example:
            >>> mapper = LibraryMapper("/arduino/framework")
            >>> mapper.convert_lib_name_to_include("WiFi")
            "esp_wifi"
            >>> mapper.convert_lib_name_to_include("BluetoothSerial")
            "bt"
        """
        # Load Arduino Core Libraries on first call
        if self._arduino_libraries_cache is None:
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
    
    def _get_arduino_core_libraries(self) -> Dict[str, str]:
        """
        Get all Arduino core libraries and their corresponding include paths.
        
        Scans the Arduino framework libraries directory to build a comprehensive
        mapping of library names to their corresponding include paths. This
        includes reading library.properties files to get official library names.
        
        Returns:
            Dict[str, str]: Dictionary mapping library names to include paths
            
        Example:
            >>> mapper = LibraryMapper("/arduino/framework")
            >>> libraries = mapper._get_arduino_core_libraries()
            >>> "wifi" in libraries
            True
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
        
        Reads the library.properties file in an Arduino library directory
        to extract the official library name as specified by the library author.
        
        Args:
            lib_dir (str): Library directory path
            
        Returns:
            Optional[str]: Library name if found, None otherwise
            
        Example:
            >>> mapper = LibraryMapper("/arduino/framework")
            >>> name = mapper._get_library_name_from_properties("/path/to/WiFi")
            >>> name
            "WiFi"
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
        
        Takes a library name and directory name and maps them to the appropriate
        ESP-IDF component include path using an extensive mapping table that
        covers both core ESP32 components and Arduino-specific libraries.
        
        Args:
            lib_name (str): Official library name from properties file
            dir_name (str): Directory name of the library
            
        Returns:
            str: Mapped include path for the ESP-IDF component
            
        Example:
            >>> mapper = LibraryMapper("/arduino/framework")
            >>> path = mapper._map_library_to_include_path("WiFi", "WiFi")
            >>> path
            "esp_wifi"
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


class BuildFileManager:
    """
    Manages backup and restoration of build files.
    
    This class handles all operations related to the pioarduino-build.py file,
    including creating backups, restoring from backups, and modifying the file
    to remove unwanted include entries for ignored libraries and components.
    
    Attributes:
        arduino_libs_mcu (str): Path to Arduino libraries for specific MCU
        mcu (str): MCU type (e.g., esp32, esp32s3, esp32c3)
        logger (ComponentLogger): Logger instance for recording operations
        
    Example:
        >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
        >>> manager.backup_pioarduino_build_py(env)
        >>> manager.restore_pioarduino_build_py()
    """
    
    def __init__(self, arduino_libs_mcu: str, mcu: str, logger: ComponentLogger):
        """
        Initialize the build file manager.
        
        Creates a new BuildFileManager with paths and configuration needed
        to manage build file operations for a specific MCU type.
        
        Args:
            arduino_libs_mcu (str): Path to Arduino libraries for specific MCU
            mcu (str): MCU type (e.g., esp32, esp32s3, esp32c3)
            logger (ComponentLogger): Logger instance for recording operations
        """
        self.arduino_libs_mcu = arduino_libs_mcu
        self.mcu = mcu
        self.logger = logger
    
    def backup_pioarduino_build_py(self, env) -> None:
        """
        Create backup of the original pioarduino-build.py.
        
        Creates a backup copy of the pioarduino-build.py file before making
        any modifications. The backup is only created if it doesn't already
        exist and only for Arduino framework projects.
        
        Args:
            env: PlatformIO environment object for framework detection
            
        Example:
            >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
            >>> manager.backup_pioarduino_build_py(env)
            # Creates pioarduino-build.py.esp32 backup file
        """
        if "arduino" not in env.subst("$PIOFRAMEWORK"):
            return
        
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        backup_path = join(self.arduino_libs_mcu, f"pioarduino-build.py.{self.mcu}")
        
        if os.path.exists(build_py_path) and not os.path.exists(backup_path):
            shutil.copy2(build_py_path, backup_path)
            self.logger.log_change(f"Created backup of pioarduino-build.py for {self.mcu}")
    
    def restore_pioarduino_build_py(self) -> None:
        """
        Restore the original pioarduino-build.py from backup.
        
        Restores the pioarduino-build.py file from its backup copy and removes
        the backup file. This effectively undoes all modifications made to
        the build file during the session.
        
        Example:
            >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
            >>> manager.restore_pioarduino_build_py()
            # Restores original file and removes backup
        """
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        backup_path = join(self.arduino_libs_mcu, f"pioarduino-build.py.{self.mcu}")
        
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, build_py_path)
            os.remove(backup_path)
            self.logger.log_change("Restored original pioarduino-build.py from backup")
    
    def remove_ignored_lib_includes(self, ignored_libs: Set[str], project_analyzer: ProjectAnalyzer) -> None:
        """
        Remove include entries for ignored libraries from pioarduino-build.py.
        
        Modifies the pioarduino-build.py file to remove CPPPATH entries for
        libraries that are marked to be ignored. Includes safety checks to
        prevent removal of libraries that are actually used in the project.
        
        Args:
            ignored_libs (Set[str]): Set of library names to ignore
            project_analyzer (ProjectAnalyzer): Analyzer to check if components are used
            
        Example:
            >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
            >>> ignored = {"unused_lib", "another_lib"}
            >>> manager.remove_ignored_lib_includes(ignored, analyzer)
        """
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        
        if not os.path.exists(build_py_path):
            return
        
        try:
            with open(build_py_path, 'r') as f:
                content = f.read()
            
            original_content = content
            total_removed = 0
            
            # Remove CPPPATH entries for each ignored library
            for lib_name in ignored_libs:
                # Universal protection: Skip if component is actually used in project
                if project_analyzer.is_component_used_in_project(lib_name):
                    self.logger.log_change(f"Skipping removal of library '{lib_name}' - detected as used in project")
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
                
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        content = re.sub(pattern, '', content)
                        total_removed += len(matches)
                        self.logger.log_change(f"Removed {len(matches)} include entries for library '{lib_name}'")
            
            # Clean up empty lines and trailing commas
            content = re.sub(r'\n\s*\n', '\n', content)
            content = re.sub(r',\s*\n\s*\]', '\n]', content)
            
            # Validate and write changes
            if self._validate_changes(original_content, content) and content != original_content:
                with open(build_py_path, 'w') as f:
                    f.write(content)
                self.logger.log_change(f"Successfully updated build file with {total_removed} total removals")
                
        except Exception as e:
            self.logger.log_change(f"Error processing ignored library includes: {str(e)}")
    
    def remove_cpppath_entries(self, removed_components: Set[str]) -> None:
        """
        Remove CPPPATH entries for removed components from pioarduino-build.py.
        
        Removes include path entries from the build file for components that
        have been explicitly removed from the project configuration. This
        helps clean up the build environment after component removal.
        
        Args:
            removed_components (Set[str]): Set of component names that were removed
            
        Example:
            >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
            >>> removed = {"esp_camera", "esp_dsp"}
            >>> manager.remove_cpppath_entries(removed)
        """
        build_py_path = join(self.arduino_libs_mcu, "pioarduino-build.py")
        
        if not os.path.exists(build_py_path):
            return
        
        try:
            with open(build_py_path, 'r') as f:
                content = f.read()
            
            original_content = content
            
            # Remove CPPPATH entries for each removed component
            for component in removed_components:
                patterns = [
                    rf'.*join\([^,]*,\s*"include",\s*"{re.escape(component)}"[^)]*\),?\n',
                    rf'.*"include/{re.escape(component)}"[^,\n]*,?\n',
                    rf'.*"[^"]*include[^"]*{re.escape(component)}[^"]*"[^,\n]*,?\n'
                ]
                
                for pattern in patterns:
                    content = re.sub(pattern, '', content)
            
            if content != original_content:
                with open(build_py_path, 'w') as f:
                    f.write(content)
                self.logger.log_change(f"Cleaned up CPPPATH entries for removed components")
                
        except Exception as e:
            self.logger.log_change(f"Error cleaning up CPPPATH entries: {str(e)}")
    
    def _validate_changes(self, original_content: str, new_content: str) -> bool:
        """
        Validate that the changes are reasonable.
        
        Performs safety checks on file modifications to ensure that the changes
        are reasonable and won't break the build system. Prevents removal of
        more than 50% of the file content.
        
        Args:
            original_content (str): Original file content before modifications
            new_content (str): Modified file content after changes
            
        Returns:
            bool: True if changes are valid and safe, False otherwise
            
        Example:
            >>> manager = BuildFileManager("/libs/esp32", "esp32", logger)
            >>> is_valid = manager._validate_changes(original, modified)
            >>> is_valid
            True  # If less than 50% of content was removed
        """
        original_lines = len(original_content.splitlines())
        new_lines = len(new_content.splitlines())
        removed_lines = original_lines - new_lines
        
        # Don't allow removing more than 50% of the file or negative changes
        return not (removed_lines > original_lines * 0.5 or removed_lines < 0)


class ComponentManager:
    """
    Manages IDF components for ESP32 Arduino framework builds with logging support.
    
    This is the main class that coordinates all component management operations
    for ESP32 Arduino framework projects. It handles component addition and removal,
    library ignore processing, build file management, and provides comprehensive
    logging of all operations.
    
    The ComponentManager integrates multiple specialized classes to provide a
    complete solution for managing ESP-IDF components in PlatformIO Arduino
    framework projects.
    
    Attributes:
        env: PlatformIO environment object
        platform: PlatformIO platform object
        config: Project configuration object
        board: Board configuration object
        mcu (str): MCU type (e.g., esp32, esp32s3)
        project_src_dir (str): Path to project source directory
        arduino_framework_dir (str): Path to Arduino framework directory
        arduino_libs_mcu (str): Path to Arduino libraries for specific MCU
        removed_components (Set[str]): Set of removed component names
        ignored_libs (Set[str]): Set of ignored library names
        logger (ComponentLogger): Logger for all operations
        yaml_handler (ComponentYamlHandler): YAML file operations handler
        project_analyzer (ProjectAnalyzer): Project dependency analyzer
        library_mapper (LibraryMapper): Library name to include path mapper
        build_file_manager (BuildFileManager): Build file operations manager
        
    Example:
        >>> manager = ComponentManager(env)
        >>> manager.handle_component_settings(add_components=True, remove_components=True)
        >>> manager.handle_lib_ignore()
        >>> manager.restore_pioarduino_build_py()
    """
    
    def __init__(self, env):
        """
        Initialize the ComponentManager with all required dependencies.
        
        Creates a new ComponentManager instance with all necessary helper classes
        and configuration. Extracts essential information from the PlatformIO
        environment and sets up the component tracking system.
        
        Args:
            env: PlatformIO environment object containing project and build information
            
        Example:
            >>> from component_manager import ComponentManager
            >>> manager = ComponentManager(env)
            >>> # Manager is now ready to handle component operations
        """
        # Core PlatformIO environment attributes
        self.env = env
        self.platform = env.PioPlatform()
        self.config = env.GetProjectConfig()
        self.board = env.BoardConfig()
        self.mcu = self.board.get("build.mcu", "esp32").lower()
        
        # Path configurations
        self.project_src_dir = env.subst("$PROJECT_SRC_DIR")
        self.arduino_framework_dir = self.platform.get_package_dir("framework-arduinoespressif32")
        self.arduino_libs_mcu = join(self.platform.get_package_dir("framework-arduinoespressif32-libs"), self.mcu)
        
        # Component tracking sets
        self.removed_components: Set[str] = set()
        self.ignored_libs: Set[str] = set()
        
        # Initialize helper classes for different responsibilities
        self.logger = ComponentLogger()
        self.yaml_handler = ComponentYamlHandler(self.logger)
        self.project_analyzer = ProjectAnalyzer(env)
        self.library_mapper = LibraryMapper(self.arduino_framework_dir)
        self.build_file_manager = BuildFileManager(self.arduino_libs_mcu, self.mcu, self.logger)
    
    def _log_change(self, message: str) -> None:
        """
        Delegate to logger for backward compatibility.
        
        Provides backward compatibility by delegating logging calls to the
        dedicated ComponentLogger instance. This maintains the same API
        while using the refactored logging system.
        
        Args:
            message (str): Message to log describing the change or operation
            
        Example:
            >>> manager = ComponentManager(env)
            >>> manager._log_change("Component operation completed")
        """
        self.logger.log_change(message)

    def handle_component_settings(self, add_components: bool = False, remove_components: bool = False) -> None:
        """
        Handle adding and removing IDF components based on project configuration.
        
        This is the main method for processing component additions and removals
        based on the custom_component_add and custom_component_remove options
        in the project configuration. It coordinates YAML file operations,
        component cleanup, and build file management.
        
        Args:
            add_components (bool): Whether to process component additions from config
            remove_components (bool): Whether to process component removals from config
            
        Example:
            >>> manager = ComponentManager(env)
            >>> # Add and remove components based on platformio.ini settings
            >>> manager.handle_component_settings(add_components=True, remove_components=True)
            >>> # Only add components
            >>> manager.handle_component_settings(add_components=True)
        """
        # Create backup before first component removal and always when a component is added
        if remove_components and not self.removed_components or add_components:
            self.build_file_manager.backup_pioarduino_build_py(self.env)
            self._log_change("Created backup of build file")
    
        # Check if env and GetProjectOption are available
        if hasattr(self, 'env') and hasattr(self.env, 'GetProjectOption'):
            component_yml_path = self.yaml_handler.get_or_create_component_yml(
                self.arduino_framework_dir, self.project_src_dir)
            component_data = self.yaml_handler.load_component_yml(component_yml_path)
    
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

            self.yaml_handler.save_component_yml(component_yml_path, component_data)
        
            # Clean up removed components
            if self.removed_components:
                self._cleanup_removed_components()

        self.handle_lib_ignore()
        
        # Print summary
        if self.logger.get_change_count() > 0:
            self._log_change(f"Session completed with {self.logger.get_change_count()} changes")
    
    def handle_lib_ignore(self) -> None:
        """
        Handle lib_ignore entries from platformio.ini and remove corresponding includes.
        
        Processes the lib_ignore configuration option to remove unwanted library
        includes from the build system. This helps reduce build time and binary
        size by excluding unused libraries while protecting critical components.
        
        Example:
            >>> manager = ComponentManager(env)
            >>> # Process lib_ignore entries from platformio.ini
            >>> manager.handle_lib_ignore()
        """
        # Create backup before processing lib_ignore
        if not self.ignored_libs:
            self.build_file_manager.backup_pioarduino_build_py(self.env)
        
        # Get lib_ignore entries from current environment only
        lib_ignore_entries = self._get_lib_ignore_entries()
        
        if lib_ignore_entries:
            self.ignored_libs.update(lib_ignore_entries)
            self.build_file_manager.remove_ignored_lib_includes(self.ignored_libs, self.project_analyzer)
            self._log_change(f"Processed {len(lib_ignore_entries)} ignored libraries")
    
    def restore_pioarduino_build_py(self, source=None, target=None, env=None) -> None:
        """
        Restore the original pioarduino-build.py from backup.
        
        Restores the build file to its original state, undoing all modifications
        made during the session. This method maintains compatibility with
        PlatformIO's callback system by accepting unused parameters.
        
        Args:
            source: Unused parameter for PlatformIO compatibility
            target: Unused parameter for PlatformIO compatibility  
            env: Unused parameter for PlatformIO compatibility
            
        Example:
            >>> manager = ComponentManager(env)
            >>> # Restore original build file
            >>> manager.restore_pioarduino_build_py()
            >>> # Can also be used as PlatformIO callback
            >>> env.AddPostAction("buildprog", manager.restore_pioarduino_build_py)
        """
        self.build_file_manager.restore_pioarduino_build_py()
    
    def _get_lib_ignore_entries(self) -> List[str]:
        """
        Get lib_ignore entries from current environment configuration only.
        
        Extracts and processes lib_ignore entries from the project configuration,
        converting library names to include directory names and filtering out
        critical ESP32 components that should never be ignored.
        
        Returns:
            List[str]: List of library names to ignore after processing and filtering
            
        Example:
            >>> manager = ComponentManager(env)
            >>> ignored = manager._get_lib_ignore_entries()
            >>> "esp_wifi" in ignored  # Only if explicitly ignored and not critical
            False  # WiFi is typically critical
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
                    include_name = self.library_mapper.convert_lib_name_to_include(entry)
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
    
    def _remove_components(self, component_data: Dict[str, Any], components_to_remove: list) -> None:
        """
        Remove specified components from the configuration.
        
        Removes components from the idf_component.yml dependencies section
        and tracks them for filesystem cleanup. Empty component names are
        automatically skipped.
        
        Args:
            component_data (Dict[str, Any]): Component configuration data from YAML
            components_to_remove (list): List of component names to remove
            
        Example:
            >>> manager = ComponentManager(env)
            >>> data = {"dependencies": {"esp_camera": {"version": "*"}}}
            >>> manager._remove_components(data, ["esp_camera"])
            >>> "esp_camera" in data["dependencies"]
            False
        """
        dependencies = component_data.setdefault("dependencies", {})
        
        for component in components_to_remove:
            component = component.strip()
            if not component:
                continue
                
            if component in dependencies:
                del dependencies[component]
                self._log_change(f"Removed component: {component}")
                
                # Track for cleanup
                filesystem_name = self._convert_component_name_to_filesystem(component)
                self.removed_components.add(filesystem_name)
    
    def _add_components(self, component_data: Dict[str, Any], components_to_add: list) -> None:
        """
        Add specified components to the configuration.
        
        Adds components to the idf_component.yml dependencies section with
        version specifications. Components that are too short (≤4 characters)
        or already exist are automatically skipped.
        
        Args:
            component_data (Dict[str, Any]): Component configuration data from YAML
            components_to_add (list): List of component entries to add (can include versions)
            
        Example:
            >>> manager = ComponentManager(env)
            >>> data = {"dependencies": {}}
            >>> manager._add_components(data, ["esp_camera@1.0.0", "esp_dsp"])
            >>> "esp_camera" in data["dependencies"]
            True
        """
        dependencies = component_data.setdefault("dependencies", {})
        
        for component in components_to_add:
            component = component.strip()
            if len(component) <= 4:  # Skip too short entries
                continue
            
            component_name, version = self._parse_component_entry(component)
            
            if component_name not in dependencies:
                dependencies[component_name] = {"version": version}
                self._log_change(f"Added component: {component_name} (version: {version})")
    
    def _parse_component_entry(self, entry: str) -> tuple[str, str]:
        """
        Parse component entry into name and version.
        
        Parses a component specification string that may include version
        information separated by '@' symbol. If no version is specified,
        defaults to wildcard version.
        
        Args:
            entry (str): Component entry string (e.g., "component@1.0.0" or "component")
            
        Returns:
            tuple[str, str]: Tuple of (component_name, version)
            
        Example:
            >>> manager = ComponentManager(env)
            >>> name, version = manager._parse_component_entry("esp_camera@1.0.0")
            >>> name, version
            ("esp_camera", "1.0.0")
            >>> name, version = manager._parse_component_entry("esp_dsp")
            >>> name, version
            ("esp_dsp", "*")
        """
        if "@" in entry:
            name, version = entry.split("@", 1)
            return (name.strip(), version.strip())
        return (entry.strip(), "*")
    
    def _convert_component_name_to_filesystem(self, component_name: str) -> str:
        """
        Convert component name from registry format to filesystem format.
        
        Converts component names from ESP-IDF component registry format
        (which uses forward slashes) to filesystem-safe format (using
        double underscores) for directory operations.
        
        Args:
            component_name (str): Component name in registry format
            
        Returns:
            str: Component name in filesystem-safe format
            
        Example:
            >>> manager = ComponentManager(env)
            >>> fs_name = manager._convert_component_name_to_filesystem("espressif/esp_camera")
            >>> fs_name
            "espressif__esp_camera"
        """
        return component_name.replace("/", "__")
    
    def _cleanup_removed_components(self) -> None:
        """
        Clean up removed components and restore original build file.
        
        Performs cleanup operations for components that have been removed,
        including removing their include directories and cleaning up
        CPPPATH entries from the build file.
        
        Example:
            >>> manager = ComponentManager(env)
            >>> # After removing components
            >>> manager._cleanup_removed_components()
            # Removes include directories and cleans build file
        """
        for component in self.removed_components:
            self._remove_include_directory(component)
        
        self.build_file_manager.remove_cpppath_entries(self.removed_components)
    
    def _remove_include_directory(self, component: str) -> None:
        """
        Remove include directory for a component.
        
        Removes the include directory for a specific component from the
        Arduino libraries directory. This helps clean up the filesystem
        after component removal.
        
        Args:
            component (str): Component name whose include directory should be removed
            
        Example:
            >>> manager = ComponentManager(env)
            >>> manager._remove_include_directory("esp_camera")
            # Removes /path/to/libs/esp32/include/esp_camera directory
        """
        include_path = join(self.arduino_libs_mcu, "include", component)
        
        if os.path.exists(include_path):
            shutil.rmtree(include_path)
            self._log_change(f"Removed include directory: {include_path}")
