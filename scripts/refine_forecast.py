from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from madrasflow.refinement import run_refinement
if __name__=='__main__':run_refinement()
