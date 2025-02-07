import json
import openai
import os


class LLM():
    def __init__(self):
        self.url = ''
        self.key = ''
        self.model = ''
        if not os.path.exists('config.json'):
            with open('config.json', 'w') as f:
                f.write('{}')


    def load_json(self):
        with open('config.json', 'r') as f:
            config = json.load(f)
        self.url = config.get('url', '')
        self.key = config.get('key', '')
        self.model = config.get('model', '')
        self.count = config.get('count', '0')


    def save_json(self):
        """Save API configuration to file"""
        if not self.url or not self.key or not self.model:
            raise ValueError("All API settings must be filled")
            
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                
            with open('config.json', 'w') as f:
                config['url'] = self.url
                config['key'] = self.key
                config['model'] = self.model
                config['count'] = self.count
                json.dump(config, f, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to save configuration: {str(e)}")


    def generate_answers(self, question, answer):
        # Initialize OpenAI client
        client = openai.Client(api_key=self.key, base_url=self.url)
        
        # Create system prompt
        system_prompt = f"""You are a helpful assistant helping user to create a quiz. Respond in the same language as the user's question. User will provide to you quiz question and a correct answer. Provide a list of incorrect answers to fill into the quiz. Format your answers as a list of items, each starting with "- ", and enclose all answers within triple backticks (```). Generate {self.count} new answers"""
        
        # Create user prompt
        user_prompt = f"# {question}\n\n```\n- {answer}\n```\n"
        
        # Generate answers using API
        answers = []
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=1000,
            n=0,
            stop=None
        )
        
        # Extract and process answers
        answer_text = response.choices[0].message.content.strip()
        
        # Check if response is properly encapsulated
        if answer_text.count('```') != 2: raise ValueError
        
        inner_content = answer_text.split('```')[1]
        
        # Split answers by lines starting with "- "
        for line in inner_content.split('\n'):
            line = line.strip()
            if line.startswith('- '):
                answers.append(line[2:].strip().strip('"'))
            
        return answers
