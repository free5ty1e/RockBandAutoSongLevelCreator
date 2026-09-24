#!/usr/bin/env python3
"""
Automated Iteration Loop

Runs the pipeline, evaluates against reference, and applies targeted fixes.
"""

import subprocess
import json
import time
from pathlib import Path
from autorb.evaluation.chart_evaluator import ChartEvaluator
from autorb.evaluation.stem_analyzer import analyze_stem_dir

class IterationLoop:
    def __init__(self, test_song_dir: Path, reference_midi: Path):
        self.test_song_dir = test_song_dir
        self.reference_midi = Path(reference_midi)
        self.iteration = 0
        self.best_metrics = {}
        
    def run_pipeline(self, output_dir: Path) -> bool:
        """Run the full pipeline."""
        cmd = [
            "python", "-m", "autorb.cli",
            str(self.test_song_dir / "audio.mp3"),
            "--artist", "Test Artist",
            "--title", "Test Song",
            "--year", "2024",
            "--genre", "Rock",
            "--lyrics", str(self.test_song_dir / "lyrics.lrc"),
            "--output-dir", str(output_dir),
            "--skip-separation"  # Use existing stems
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return result.returncode == 0
    
    def evaluate(self, gen_midi: Path) -> dict:
        """Run evaluation against reference."""
        evaluator = ChartEvaluator()
        results = evaluator.evaluate(self.reference_midi, Path("/workspaces/RockBandAutoSongLevelCreator/output/validation/notes.mid"))
        
        # Calculate aggregate score
        total_ref = sum(m.total_ref_notes for m in results.values())
        total_matched = sum(m.matched_notes for m in results.values())
        total_fp = sum(m.false_positives for m in results.values())
        total_fn = sum(m.false_negatives for m in results.values())
        
        precision = sum(m.matched_notes for m in results.values()) / max(sum(m.total_gen_notes for m in results.values()), 1)
        recall = sum(m.matched_notes for m in results.values()) / max(sum(m.total_ref_notes for m in results.values()), 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        
        return {
            'results': results,
            'f1': f1,
            'precision': precision,
            'recall': recall,
            'total_matched': total_matched,
            'total_fp': total_fp,
            'total_fn': total_fn
        }
    
    def analyze_failures(self, eval_results: dict) -> list:
        """Analyze failures and generate fix hypotheses."""
        hypotheses = []
        
        for key, metrics in results.items():
            if metrics.total_ref_notes == 0:
                continue
                
            recall = metrics.matched_notes / max(metrics.total_ref_notes, 1)
            precision = metrics.matched_notes / max(metrics.total_gen_notes, 1)
            
            if recall < 0.5:
                hypotheses.append({
                    'instrument': metrics.instrument,
                    'difficulty': metrics.difficulty,
                    'issue': f'Low recall ({recall:.1%}) - missing {metrics.false_negatives} notes',
                    'priority': 'high'
                })
            
            if metrics.false_positives > metrics.total_ref_notes * 0.5:
                hypotheses.append({
                    'instrument': metrics.instrument,
                    'difficulty': metrics.difficulty,
                    'issue': f'High false positives ({metrics.false_positives}) - over-charting',
                    'priority': 'high'
                })
            
            if metrics.onset_accuracy_ms > 100:
                hypotheses.append({
                    'instrument': metrics.instrument,
                    'difficulty': metrics.difficulty,
                    'issue': f'Timing error {metrics.onset_accuracy_ms:.0f}ms avg',
                    'priority': 'medium'
                })
            
            if metrics.lane_accuracy < 0.5:
                hypotheses.append({
                    'instrument': metrics.instrument,
                    'difficulty': metrics.difficulty,
                    'issue': f'Lane accuracy {metrics.lane_accuracy:.0%}',
                    'priority': 'high'
                })
        
        return hypotheses
    
    def apply_fix(self, hypothesis: dict) -> bool:
        """Apply a targeted fix based on hypothesis."""
        # This would modify source code based on hypothesis
        # For now, return False to indicate manual intervention needed
        return False
    
    def run_iteration(self, output_dir: Path) -> dict:
        """Run one iteration of the loop."""
        self.iteration += 1
        print(f"\n{'='*60}")
        print(f"ITERATION {self.iteration}")
        print(f"{'='*60}")
        
        # Run pipeline
        print("Running pipeline...")
        success = self.run_pipeline(self.output_dir)
        
        if not success:
            return {'success': False, 'error': 'Pipeline failed'}
        
        # Evaluate
        print("Evaluating...")
        eval_results = self.evaluate(self.output_dir / "validation" / "notes.mid")
        
        # Analyze
        hypotheses = self.analyze_failures(eval_results['results'])
        
        print(f"\nIteration {self.iteration} Results:")
        print(f"  F1: {eval_results['f1']:.3f}")
        print(f"  Precision: {eval_results['precision']:.3f}")
        print(f"  Recall: {eval_results['recall']:.3f}")
        print(f"  Hypotheses generated: {len(hypotheses)}")
        
        for h in hypotheses[:5]:
            print(f"  [{h['priority']}] {h['instrument']} {h['difficulty']}: {h['issue']}")
        
        return {
            'iteration': self.iteration,
            'eval_results': eval_results,
            'hypotheses': hypotheses
        }

def run_automated_iterations(test_song: str, max_iterations: int = 10):
    """Run automated iteration loop."""
    # TODO: Implement full automation
    pass

if __name__ == "__main__":
    print("Iteration loop framework ready")
    print("Next steps:")
    print("1. Create test song directory with audio.mp3 and lyrics.lrc")
    print("2. Set reference_midi to known good chart for same song")
    print("3. Run loop.run_iteration() in a loop")