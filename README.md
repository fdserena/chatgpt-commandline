
Deprecation: v1 beta version of Assistants API shutting down on December 18, 2024

The program will not work!


chatgpt-commandline
donate please

assumes::: python3

assumes:::  pip install openai==1.20.0

try:
python openai-commandline.py run -c openai-template-prev-lie.config 
openai-template-prev-tru.config

type: + new_thread -c 1

type: + join2_thread 1 0

type: this statement is true.  repeat this everytime you write a response

type: this statement is false.  repeat this everytime you write a response

type: + quit_all


note the responses

then when done:
python openai-commandline.py delete -c openai-template-prev-lie.config 
openai-template-prev-tru.config

also try:
python openai-commandline.py run -c openai-template.config

then when done:
python openai-commandline.py delete  -c openai-template.config

