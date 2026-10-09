#!/usr/bin/env python3
"""
Automated Iteration Runner

Runs the full pipeline -> evaluate -> fix -> repeat loop.
"""

import subprocess
import json
import time
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, "/workspaces/RockBandAutoSongLevelCreator")
from autorb.evaluation.chart_evaluator import ChartEvaluator
from autorb.evaluation.stem_analyzer import analyze_stem_dir, StemQualityMetrics

class IterationRunner:
    def __init__(self, audio_file: Path, lyrics_file: Path, reference_midi: Path = None):
        self.audio_file = Path(audio_file)
        self.lyrics_file = Path(lyrics_file)
        self.reference_midi = Path(reference_midi) if reference_midi else None
        self.output_base = Path("/tmp/autorun_iterations")
        self.iteration = 0
        self.history = []
        
    def run_pipeline(self, output_dir: Path, extra_args: list = None) -> bool:
        """Run the full pipeline."""
        cmd = [
            "python", "-m", "autorb.cli",
            "--artist", "Eve 6",
            "--title", "Open Road Song",
            "--year", "1998",
            "--genre", "Alternative",
            "--lyrics", str(self.lyrics_file),
            "--output-dir", str(self.output_dir),
            "--skip-separation"
        ]
        
        if extra_args:
            cmd.extend(extra_args)
        
        env = {"PYTHONPATH": "/workspaces/RockBandAutoSongLevelCreator"}
        result = subprocess.run(
            ["python", "-m", "autorb.cli",
             str(self.audio_file),
             "--artist", "Eve 6",
             "--title", "Open Road Song",
             "--year", "1998",
             "--genre", "Alternative",
             "--lyrics", str(self.lyrics_file),
             "--output-dir", str(self.output_dir),
             "--skip-separation"],
            cwd="/workspaces/RockBandAutoSongLevelCreator",
            capture_output=True, text=True, timeout=600
        )
        return result.returncode == 0, result.stdout, result.stderr
    
def evaluate(self) -> dict:
        """Evaluate generated chart against reference."""
        # If no reference, use golden master from first iteration
        if not self.reference_midi or not self.reference_midi.exists():
            golden_master = self.output_base / "golden_master.mid"
            if golden_master.exists():
                self.reference_midi = golden_master
            else:
                # First iteration - save as golden master
                gen_midi = self.output_dir / "validation" / "notes.mid"
                if gen_midi.exists():
                    golden_master.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(gen_midi, golden_master)
                    print(f"Created golden master at {golden_master}")
                return {"error": "No reference MIDI - created golden master", "f1": 0, "precision": 0, "recall": 0}
        
        evaluator = ChartEvaluator()
        gen_midi = self.output_dir / "validation" / "notes.mid"
        
        if not gen_midi.exists():
            return {"error": f"Generated MIDI not found at {gen_midi}"}
        
        results = evaluator.evaluate(self.reference_midi, gen_midi)
        
        # Calculate aggregate metrics
        total_ref = sum(m.total_ref_notes for m in results.values())
        total_gen = sum(m.total_gen_notes for m in results.values())
        total_matched = sum(m.matched_notes for m in results.values())
        total_fp = sum(m.false_positives for m in results.values())
        total_fn = sum(m.false_negatives for m in results.values())
        
        precision = sum(m.matched_notes for m in results.values()) / max(sum(m.total_gen_notes for m in results.values()), 1)
        recall = sum(m.matched_notes for m in results.values()) / max(sum(m.total_ref_notes for m in results.values()), 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        
        return {
            'per_instrument': {k: v.__dict__ for k, v in results.items()},
            'f1': f1,
            'precision': precision,
            'recall': recall,
            'total_matched': sum(m.matched_notes for m in results.values()),
            'total_fp': sum(m.false_positives for m in results.values()),
            'total_fn': sum(m.false_negatives for m in results.values()),
            'total_ref': sum(m.total_ref_notes for m in results.values()),
            'total_gen': sum(m.total_gen_notes for m in results.values())
        }
    
    def analyze_stems(self) -> dict:
        """Analyze stem quality."""
        return analyze_stem_dir(self.output_dir / "stems")
    
    def generate_fix_hypotheses(self, eval_results: dict) -> list:
        """Generate fix hypotheses from evaluation results."""
        hypotheses = []
        
        for key, metrics in eval_results.get('per_instrument', {}).items():
            if metrics['total_ref_notes'] == 0:
                continue
                
            recall = metrics['matched_notes'] / max(metrics['total_ref_notes'], 1)
            precision = metrics['matched_notes'] / max(metrics['total_gen_notes'], 1)
            lane_acc = metrics['lane_accuracy']
            onset_acc = metrics['onset_accuracy_ms']
            
            if metrics['total_ref_notes'] > 0 and metrics['matched_notes'] / max(metrics['total_ref_notes'], 1) < 0.5:
                self._add_hypothesis(hypotheses, 'high', 
                    f"Low recall ({recall:.1%}) - missing {metrics['false_negatives']} notes",
                    'recall')
            
            if metrics['false_positives'] > metrics['total_ref_notes'] * 0.5:
                self._add_hypothesis(hypotheses, 'high',
                    f"High false positives ({metrics['false_positives']}) - over-charting",
                    'precision')
            
            if metrics['onset_accuracy_ms'] > 100:
                self._add_hypothesis(hypotheses, 'medium',
                    f"Timing error {metrics['onset_accuracy_ms']:.0f}ms avg",
                    'timing')
            
            if metrics['lane_accuracy'] < 0.5:
                self._add_hypothesis(hypotheses, 'high',
                    f"Lane accuracy {metrics['lane_accuracy']:.0%}",
                    'lane')
        
        return hypotheses
    
    def _add_hypothesis(self, hypotheses, priority, issue, category):
        hypotheses.append({
            'priority': priority,
            'issue': issue,
            'category': category,
            'timestamp': time.time()
        })
    
    def _print_summary(self, eval_results: dict):
        """Print evaluation summary."""
        if 'error' in eval_results:
            print(f"  Evaluation error: {eval_results['error']}")
            return
        
        print(f"\n  F1 Score: {eval_results.get('f1', 0):.3f}")
        print(f"  Precision: {eval_results.get('precision', 0):.3f}")
        print(f"  Recall: {eval_results.get('recall', 0):.3f}")
        
        for key, metrics in eval_results.get('per_instrument', {}).items():
            if metrics.get('total_ref_notes', 0) > 0:
                print(f"  {metrics['instrument']} {metrics['difficulty']}: "
                      f"P={metrics['lane_accuracy']:.1%} "
                      f"onset={metrics['onset_accuracy_ms']:.0f}ms "
                      f"FP={metrics['false_positives']} FN={metrics['false_negatives']}")
    
    def run_iteration(self, iteration_dir: Path, extra_args: list = None) -> dict:
        """Run one full iteration: pipeline -> evaluate -> analyze."""
        self.output_dir = Path("/tmp/autorun_iterations") / f"iter_{self.iteration}"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"ITERATION {self.iteration}")
        print(f"{'='*60}")
        
        # 1. Run pipeline
        print(f"\n[Iteration {self.iteration}] Running pipeline...")
        success, stdout, stderr = self.run_pipeline(self.output_dir)
        
        if not success:
            return {'success': False, 'error': 'Pipeline failed'}
        
        # 2. Evaluate
        print("Evaluating...")
        eval_results = self.evaluate()
        
        # 3. Analyze stems
        print("Analyzing stems...")
        stem_analysis = self.analyze_stems()
        
        # 4. Generate hypotheses
        hypotheses = self.generate_fix_hypotheses(eval_results)
        
        # Record history
        iteration_record = {
            'iteration': self.iteration,
            'timestamp': time.time(),
            'eval_results': eval_results,
            'stem_analysis': stem_analysis,
            'hypotheses': hypotheses
        }
        self.history.append(iteration_record)
        
        # Print summary
        self._print_summary(eval_results)
        
        return {
            'success': True,
            'eval_results': eval_results,
            'stem_analysis': stem_analysis,
            'hypotheses': hypotheses
        }
    
    def _check_convergence(self) -> bool:
        """Check if we've converged (no significant improvements)."""
        if len(self.history) < 2:
            return False
        
        last = self.history[-1]['eval_results']
        prev = self.history[-2]['eval_results']
        
        if 'f1' not in last or 'f1' not in prev:
            return False
        
        f1_improvement = last['f1'] - prev['f1']
        return f1_improvement < 0.01  # Less than 1% improvement
    
    def run(self, max_iterations: int = 10):
        """Run the full iteration loop."""
        print(f"Starting iteration loop for {self.audio_file}")
        print(f"Reference MIDI: {self.reference_midi}")
        
        for i in range(max_iterations):
            self.iteration = i
            result = self.run_iteration(self.output_base / f"iter_{i}")
            
            if not result['success']:
                print(f"Iteration {i} failed: {result.get('error')}")
                break
            
            # Save iteration results
            with open(self.output_base / f"iter_{i}_results.json", 'w') as f:
                json.dump(result, f, indent=2, default=str)
            
            # Check if we've converged
            if self._check_convergence():
                print(f"\nConverged at iteration {i}!")
                break
        
        # Save full history
        with open(self.output_base / "history.json", 'w') as f:
            json.dump(self.history, f, indent=2, default=str)
        
        print(f"\nIteration loop complete. Results in {self.output_base}")

if __name__ == "__main__":
    import sys
    import time
    from pathlib import Path
    
    # Configuration
    audio_file = Path("input/eve6-openRoadSong.mp3")
    lyrics_file = Path("input/eve6-openRoadSong.lrc")
    reference_midi = None  # No reference for this song yet
    
    runner = IterationRunner(
        audio_file=Path("input/eve6-openRoadSong.mp3"),
        lyrics_file=Path("input/eve6-openRoadSong.lrc"),
        reference_midi=None
    )
    
    # Run 5 iterations
    runner.run(max_iterations=5)