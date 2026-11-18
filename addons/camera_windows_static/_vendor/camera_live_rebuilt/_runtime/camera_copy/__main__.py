"""Private SAVED_DISK helper, not public blenderctl."""
import argparse
import json
from . import apply_saved_candidate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-path','expected-source-sha','candidate-path','expected-candidate-sha','new-output-directory','trusted-blender-path','expected-binary-sha'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(apply_saved_candidate(**vars(args)),indent=2))
if __name__=='__main__':main()
