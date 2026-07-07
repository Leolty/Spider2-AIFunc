import random
import json
import os
import time
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import threading
import glob
from copy import deepcopy

from file_manager import FileManager
from message_processor import MessageProcessor
from prompt_builders import get_prompt_builder

class LLMAgent:
    def __init__(self, args):
        self.args = args
        self.model_client = OpenAI(
            base_url=os.getenv("OPENAI_API_BASE"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        
        self.file_manager = FileManager(args)
        self.message_processor = MessageProcessor(args)
        
        self.prompt_builder = get_prompt_builder(args.prompt_strategy)
        
        self.processed_instances = defaultdict(int)
        
    def call_llm(self, messages, instance_id=None, round_num=None):
        """Call LLM with retry mechanism"""
        max_retries = 10
        retry_count = 0
        
        reasoning_effort = os.getenv("REASONING_EFFORT", "").strip().lower()
        api_base = os.getenv("OPENAI_API_BASE", "")
        is_openrouter = "openrouter.ai" in api_base
        openrouter_provider = os.getenv("OPENROUTER_PROVIDER", "").strip()

        while retry_count < max_retries:
            try:
                kwargs = dict(
                    model=self.args.model,
                    messages=messages,
                    max_completion_tokens=self.args.max_new_tokens,
                    n=1,
                )

                if reasoning_effort in ("xhigh", "high", "medium", "low", "minimal"):
                    kwargs["temperature"] = 1
                    if is_openrouter:
                        extra = {"reasoning": {"effort": reasoning_effort}}
                        if openrouter_provider:
                            extra["provider"] = {"order": [openrouter_provider], "allow_fallbacks": False}
                        kwargs["extra_body"] = extra
                    else:
                        model_lower = self.args.model.lower()
                        if "gpt" in model_lower or "openai" in model_lower:
                            kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}
                        else:
                            kwargs["extra_body"] = {"reasoning": {"effort": reasoning_effort}}
                else:
                    kwargs["temperature"] = self.args.temperature
                    kwargs["top_p"] = self.args.top_p
                    if is_openrouter and openrouter_provider:
                        kwargs["extra_body"] = {"provider": {"order": [openrouter_provider], "allow_fallbacks": False}}

                response = self.model_client.chat.completions.create(**kwargs)
                
                content = response.choices[0].message.content
                if content:
                    return content
                else:
                    raise Exception("Empty response content")
                    
            except Exception as e:
                retry_count += 1
                instance_info = f" for {instance_id}" if instance_id else ""
                round_info = f" (round {round_num})" if round_num is not None else ""
                print(f"LLM Error{instance_info}{round_info}: {e}. Retrying ({retry_count}/{max_retries})...")
                
                if retry_count >= max_retries:
                    return f"ERROR: Failed to get response after {max_retries} retries"
                
                time.sleep(min(0.5 * (2 ** retry_count), 60))
        
        return "ERROR: Unexpected exit from retry loop"
    
    def process_single_item(self, item, rollout_idx):
        """Process a single item with specified rollout index"""
        instance_id = item["instance_id"]

        if self.processed_instances[instance_id] >= self.args.rollout_number:
            print(f"Skipping {instance_id} rollout {rollout_idx + 1} (already completed {self.processed_instances[instance_id]} valid rollouts)")
            return None
        
        try:
            messages = self.prompt_builder.build_initial_prompt(item, self.args)
            conversation_history = deepcopy(messages)
            terminated = False
            
            for round_num in range(self.args.max_rounds):
                print(f"Processing {instance_id} rollout {rollout_idx + 1}, round {round_num + 1}")

                llm_response = self.call_llm(messages, instance_id, round_num + 1)
                
                if os.environ.get('DEBUG'):
                    print(f"\n{'='*60}")
                    print(f"[DEBUG] {instance_id} round {round_num + 1} - LLM response:")
                    print(f"{'='*60}")
                    print(llm_response[:2000])
                    if len(llm_response) > 2000:
                        print(f"... ({len(llm_response) - 2000} more chars)")
                    print(f"{'='*60}\n")
                
                if llm_response.startswith("ERROR:"):
                    print(f"Failed to get valid LLM response for {instance_id}")
                    error_result = {
                        "instance_id": instance_id,
                        "rollout_idx": rollout_idx,
                        "error": llm_response,
                        "round_failed": round_num + 1,
                        "terminated": False
                    }
                    self.file_manager.add_single_result(error_result)
                    return error_result
                
                result = self.message_processor.process_round(
                    llm_response, item, messages, conversation_history,
                    round_num=round_num + 1, max_rounds=self.args.max_rounds
                )
                
                if result.get("terminated"):
                    terminated = True
                    break
                
                if result.get("continue"):
                    continue
            
            result = {
                "instance_id": instance_id,
                "rollout_idx": rollout_idx,
                "conversation": conversation_history,
                "final_messages": messages,
                "terminated": terminated
            }
            
            self.file_manager.add_single_result(result)
            
            status = "TERMINATED" if terminated else "INCOMPLETE"
            print(f"Completed: {instance_id} (rollout {rollout_idx + 1}/{self.args.rollout_number}) - {status}")
            
            return result
            
        except Exception as e:
            error_result = {
                "instance_id": instance_id,
                "rollout_idx": rollout_idx,
                "error": str(e),
                "terminated": False
            }
            
            self.file_manager.add_single_result(error_result)
            print(f"Error processing {instance_id} rollout {rollout_idx + 1}: {str(e)}")
            return error_result
    
    def run(self):
        """Main execution function"""
        existing_results = self.file_manager.load_existing_results()
        self.processed_instances = self.file_manager.processed_instances
        os.makedirs(self.args.output_folder, exist_ok=True)
        
        with open(self.args.input_file, 'r', encoding='utf-8') as f:
            items = [json.loads(line) for line in f]

        random.shuffle(items)
        
        tasks_to_process = []
        for item in items:
            instance_id = item["instance_id"]
            current_valid_rollouts = self.processed_instances[instance_id]
            
            for rollout_idx in range(current_valid_rollouts, self.args.rollout_number):
                tasks_to_process.append((item, rollout_idx))
        
        total_expected = len(items) * self.args.rollout_number
        total_existing = sum(self.processed_instances.values())
        
        print(f"Total items: {len(items)}")
        print(f"Rollout number: {self.args.rollout_number}")
        print(f"Prompt strategy: {self.args.prompt_strategy}")
        print(f"Total expected tasks: {total_expected}")
        print(f"Valid completed tasks: {total_existing}")
        print(f"Tasks to process: {len(tasks_to_process)}")
        
        if not tasks_to_process:
            print("All rollouts have been completed successfully!")
            return
        
        completed_count = 0
        with ThreadPoolExecutor(max_workers=self.args.num_threads) as executor:
            future_to_task = {
                executor.submit(self.process_single_item, item, rollout_idx): (item, rollout_idx)
                for item, rollout_idx in tasks_to_process
            }
            
            for future in as_completed(future_to_task):
                item, rollout_idx = future_to_task[future]
                try:
                    result = future.result()
                    if result is not None:
                        completed_count += 1
                        print(f"Progress: {completed_count}/{len(tasks_to_process)} completed")
                except Exception as e:
                    print(f"Unexpected error processing {item['instance_id']} rollout {rollout_idx + 1}: {str(e)}")
        
        print(f"All processing completed! Results saved to: {self.args.output_folder}")
        print(f"Total processed in this run: {completed_count}")