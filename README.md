chatgpt-commandline
donate please

assumes python3

try:
python openai-commandline.py run -c openai-template-prev-lie.config 
openai-template-prev-tru.config

then when done:
python openai-commandline.py delete -c openai-template-prev-lie.config 
openai-template-prev-tru.config

also try:
python openai-commandline.py run -c openai-template.config

then when done:
python openai-commandline.py delete  -c openai-template.config

