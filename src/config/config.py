import json
import os
import re
import yaml
from src.utils import AsyncLLM

class Config:
    def __init__(self, config_file_path=None, config_dict={}):
        # load default config
        current_path = os.path.dirname(os.path.realpath(__file__))
        default_file_path = os.path.join(current_path, "default_config.yaml")
        self.config = self._load_config(default_file_path, resolve_env=False)

        # load from file
        self.config_file_path = config_file_path
        if config_file_path is not None:
            file_config = self._load_config(config_file_path, resolve_env=False)
            self._merge(self.config, file_config)
        
        # load from dict
        self._merge(self.config, config_dict)
        
        self.config = self._resolve_env(self.config)
        self._set_dirs()
        self._set_llms()
        self._set_rate_limiter()

    
    @staticmethod
    def _merge(target, incoming):
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                Config._merge(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _resolve_env(obj):
        if isinstance(obj, dict):
            return {k: Config._resolve_env(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [Config._resolve_env(v) for v in obj]
        if isinstance(obj, str):
            def replace(match):
                value = os.getenv(match.group(1))
                if value is None:
                    raise ValueError(f"Environment variable '{match.group(1)}' is not set")
                return value
            return re.sub(r'\$\{([^}]+)\}', replace, obj)
        return obj

    def _load_config(self, config_file_path, resolve_env=True):
        def build_yaml_loader():
            loader = yaml.FullLoader
            loader.add_implicit_resolver(
                "tag:yaml.org,2002:float",
                re.compile(
                    """^(?:
                [-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?
                |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
                |\\.[0-9_]+(?:[eE][-+][0-9]+)?
                |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\\.[0-9_]*
                |[-+]?\\.(?:inf|Inf|INF)
                |\\.(?:nan|NaN|NAN))$""",
                    re.X,
                ),
                list("-+0123456789."),
            )
            return loader
    
        yaml_loader = build_yaml_loader()
        file_config = dict()
        if os.path.exists(config_file_path):
            if config_file_path.endswith('.yaml'):
                with open(config_file_path, "r", encoding="utf-8") as f:
                    file_config.update(yaml.load(f.read(), Loader=yaml_loader))
            elif config_file_path.endswith('.json'):
                with open(config_file_path, 'r') as f:
                    file_config.update(json.load(f))
            else:
                raise ValueError(f"Unsupported file type: {config_file_path}")
        else:
            raise ValueError(f"Config file not found: {config_file_path}")
        
        # Replace environment variables in the loaded config
        file_config = self._resolve_env(file_config) if resolve_env else file_config
        return file_config
    
    
    
    def _set_dirs(self):
        # convert output dir to absolute path
        output_dir = self.config.get('output_dir', './outputs')
        self.config['output_dir'] = output_dir
        target = self.config.get('target_name', 'unknown')
        save_note = self.config.get('save_note', None)
        target = target[:50]
        if save_note:
            target = str(save_note) + '_' + target
        self.working_dir = os.path.join(output_dir, target)
        self.config['working_dir'] = self.working_dir
        os.makedirs(self.working_dir, exist_ok=True)
        with open(os.path.join(self.working_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
        
    
    def _set_llms(self):
        llm_config_list = self.config.get('llm_config_list', [])
        llm_dict = {}
        for llm_config in llm_config_list:
            model_name = llm_config['model_name']
            llm = AsyncLLM(
                base_url=llm_config['base_url'],
                api_key=llm_config['api_key'],
                model_name=model_name,
                generation_params=llm_config.get('generation_params', {})
            )
            llm_dict[model_name] = llm
        self.llm_dict = llm_dict
            
    def _set_rate_limiter(self):
        """Initialize the global rate limiter from config."""
        from src.utils.rate_limiter import RateLimiter
        rate_limits = self.config.get('rate_limits', {})
        self.rate_limiter = RateLimiter(rate_limits)

    def __str__(self):
        return str(self.config)
