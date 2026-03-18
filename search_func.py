import pkgutil
import importlib

def find_func(package_name, func_name):
    try:
        package = importlib.import_module(package_name)
        if hasattr(package, func_name):
            print(f"Found {func_name} in {package_name}")
            return
        
        for loader, module_name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, func_name):
                    print(f"Found {func_name} in {module_name}")
            except Exception:
                continue
    except Exception as e:
        print(f"Error checking {package_name}: {e}")

if __name__ == "__main__":
    for module in pkgutil.iter_modules():
        find_func(module.name, "technical_indicators")
