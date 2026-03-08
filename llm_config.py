import os
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

def get_claude_model(temperature=0.2):
    """
    Returns the Claude 3.5 Sonnet model according to the prompt configurations.
    Used for code review, incident response, documentation, security audit etc.
    """
    return ChatAnthropic(
        model_name="claude-3-5-sonnet-20240620", 
        temperature=temperature
    )

def get_gpt4o_model(temperature=0.2):
    """
    Returns the GPT-4o model according to the prompt configurations.
    Used for CI monitoring, infra optimization, etc.
    """
    return ChatOpenAI(
        model_name="gpt-4o", 
        temperature=temperature
    )
