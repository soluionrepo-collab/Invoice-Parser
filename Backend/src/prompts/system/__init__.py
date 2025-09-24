from pathlib import Path
from jinja2 import FileSystemLoader, Environment, Template
  
def get_prompt_template(prompt_file_name: str) -> Template:
    """
    Loads a Jinja2 template from the current directory.
 
    This function initializes a Jinja2 Environment with the current file's
    directory as the template loader, and then loads the template specified
    by `prompt_file_name`.
 
    Parameters:
        prompt_file_name (str): The name of the Jinja2 template file to load.
 
    Returns:
        Template: A Jinja2 Template object that can be rendered with variables.
    """
    curr_dir = Path(__file__).parent
    env = Environment(loader=FileSystemLoader(curr_dir),variable_start_string='<<',variable_end_string='>>')
    return env.get_template(prompt_file_name)