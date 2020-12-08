import sys
import os
import numpy as np
from scipy import ndimage
import skimage
import skimage.morphology
import skimage.measure
from subprocess import call
from cytomine.models import Job
from biaflows import CLASS_OBJSEG
from biaflows.helpers import BiaflowsJob, prepare_data, upload_data, upload_metrics


def label_objects(img, threshold=0.9):
    """
    Threshold ilastik probability map and convert binary data to objects
    """
    img = img[:,1,:,:]
    img[img>=threshold] = 1.0
    img[img<threshold] = 0.0
    img = skimage.measure.label(img).astype(np.uint16)
    #img = skimage.morphology.remove_small_objects(img, int(3*min_radius*min_radius))
    
    return img

def main(argv):
    base_path = "{}".format(os.getenv("HOME")) # Mandatory for Singularity
    problem_cls = CLASS_OBJSEG

    with BiaflowsJob.from_cli(argv) as nj:
        nj.job.update(status=Job.RUNNING, progress=0, statusComment="Initialisation...")
        # 1. Prepare data for workflow
        in_imgs, gt_imgs, in_path, gt_path, out_path, tmp_path = prepare_data(problem_cls, nj, **nj.flags)

        temp_img = skimage.io.imread(os.path.join(in_path,"{}".format(in_imgs[0].filename)))
        classification_project = "/app/PixelClassification3D.ilp"

        # 2. Run ilastik prediction
        nj.job.update(progress=25, statusComment="Launching workflow...")
        shArgs = [
            "/app/ilastik/run_ilastik.sh",
            "--headless",
            "--project="+classification_project,
            "--export_source=Probabilities",
            "--output_format='multipage tiff'",
            '--output_filename_format='+os.path.join(tmp_path,'{nickname}.tiff')
            ]
        shArgs += [image.filepath for image in in_imgs]
        
        call_return = call(" ".join(shArgs), shell=True)

        # Threshold probabilites
        for image in in_imgs:
            fn = os.path.join(tmp_path,"{}.tiff".format(image.filename[:-4]))
            outfn = os.path.join(out_path,"{}".format(image.filename))
            img = skimage.io.imread(fn)
            img = label_objects(img, nj.parameters.probability_threshold)
            skimage.io.imsave(outfn, img)

        # 3. Upload data to Cytomine
        upload_data(problem_cls, nj, in_imgs, out_path, is_2d=False, **nj.flags, monitor_params={
            "start": 60, "end": 90, "period": 0.1,
            "prefix": "Extracting and uploading polygons from masks"})
        
        # 4. Compute and upload metrics
        nj.job.update(progress=90, statusComment="Computing and uploading metrics...")
        upload_metrics(problem_cls, nj, in_imgs, gt_path, out_path, tmp_path, **nj.flags)

        # 5. Pipeline finished
        nj.job.update(progress=100, status=Job.TERMINATED, status_comment="Finished.")


if __name__ == "__main__":
    main(sys.argv[1:])
