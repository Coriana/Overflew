from app import db


class AIPersonality(db.Model):
    __tablename__ = 'ai_personalities'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    expertise = db.Column(db.String(128), nullable=False)  # Comma-separated list of expertise areas
    personality_traits = db.Column(db.String(256), nullable=False)  # Comma-separated list of traits
    interaction_style = db.Column(db.String(128), nullable=False)  # How the AI tends to interact
    helpfulness_level = db.Column(db.Integer, nullable=False)  # 1-10 scale
    strictness_level = db.Column(db.Integer, nullable=False)  # 1-10 scale
    verbosity_level = db.Column(db.Integer, nullable=False)  # 1-10 scale
    avatar_url = db.Column(db.String(256))
    prompt_template = db.Column(db.Text, nullable=False)  # Template used to generate the AI response
    use_custom_prompt = db.Column(db.Boolean, default=False)  # Whether to use custom prompt or standard template
    custom_api_key = db.Column(db.String(256))  # Custom API key for this personality
    custom_base_url = db.Column(db.String(256))  # Custom base URL for this personality
    custom_model = db.Column(db.String(128))  # Custom model for this personality
    activity_frequency = db.Column(db.Float, default=0.7)  # Probability of responding to a post
    is_active = db.Column(db.Boolean, default=True)  # Whether this personality is active
    
    def __repr__(self):
        return f'<AIPersonality {self.name}>'
    
    def should_respond(self):
        """Determine if this AI personality should respond to a post based on activity frequency"""
        import random
        return random.random() < self.activity_frequency
    
    def format_prompt(self, content, context=None):
        """Format the prompt template with the content and context"""
        from app.models.site_settings import SiteSettings
        
        # If not using custom prompt, use the standard template
        if not self.use_custom_prompt:
            standard_template = SiteSettings.get('ai_standard_prompt_template')
            if standard_template:
                prompt = standard_template
            else:
                # Fallback to the personality's template if standard template is not set
                prompt = self.prompt_template
        else:
            # Use custom prompt template
            prompt = self.prompt_template
            
        if context:
            prompt = prompt.replace('{{context}}', context)
        else:
            prompt = prompt.replace('{{context}}', '')
            
        prompt = prompt.replace('{{content}}', content)
        prompt = prompt.replace('{{name}}', self.name)
        prompt = prompt.replace('{{description}}', self.description)
        prompt = prompt.replace('{{expertise}}', self.expertise)
        prompt = prompt.replace('{{personality_traits}}', self.personality_traits)
        prompt = prompt.replace('{{interaction_style}}', self.interaction_style)
        prompt = prompt.replace('{{helpfulness_level}}', str(self.helpfulness_level))
        prompt = prompt.replace('{{strictness_level}}', str(self.strictness_level))
        prompt = prompt.replace('{{verbosity_level}}', str(self.verbosity_level))
        
        return prompt
