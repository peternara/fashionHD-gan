from __future__ import division, print_function

import torch
from data.data_loader import CreateDataLoader
from options.pose_transfer_options import TestPoseTransferOptions
from misc.visualizer import GANVisualizer_V3
from misc.loss_buffer import LossBuffer

import util.io as io
import os
import sys
import time
import numpy as np
import cv2
from collections import OrderedDict
import tqdm


opt = TestPoseTransferOptions().parse()
train_opt = io.load_json(os.path.join('checkpoints', opt.id, 'train_opt.json'))
preserved_opt = {'gpu_ids', 'is_train'}
for k, v in train_opt.iteritems():
    if k in opt and (k not in preserved_opt):
        setattr(opt, k, v)
# create model
if opt.which_model_T in {'unet', 'resnet'}:
    from models.supervised_pose_transfer_model import SupervisedPoseTransferModel
    model = SupervisedPoseTransferModel()
elif opt.which_model_T == 'vunet':
    from models.vunet_pose_transfer_model import VUnetPoseTransferModel
    model = VUnetPoseTransferModel()
elif opt.which_model_T == '2stage':
    from models.two_stage_pose_transfer_model import TwoStagePoseTransferModel
    model = TwoStagePoseTransferModel()
else:
    raise NotImplementedError()

model.initialize(opt)
# create data loader
# train_loader = CreateDataLoader(opt, split = 'train')
val_loader = CreateDataLoader(opt, split = 'test')
# create visualizer
visualizer = GANVisualizer_V3(opt)

pavi_upper_list = ['PSNR', 'SSIM']
pavi_lower_list = ['loss_L1', 'loss_content', 'loss_style', 'loss_G', 'loss_D', 'loss_pose', 'loss_kl']

# visualize
if opt.test_nvis > 0:
    print('visualizing first %d samples' % opt.test_nvis)
    num_vis_batch = int(np.ceil(1.0*opt.test_nvis/opt.batch_size))
    val_visuals = None
    for i, data in enumerate(val_loader):
        if i == num_vis_batch:
            break
        model.set_input(data)
        model.test(compute_loss=False)
        visuals = model.get_current_visuals()
        if val_visuals is None:
            val_visuals = visuals
        else:
            for name, v in visuals.iteritems():
                val_visuals[name][0] = torch.cat((val_visuals[name][0], v[0]),dim=0)
    visualizer.visualize_image(epoch = opt.which_epoch, subset = 'test', visuals = val_visuals)

if opt.test_nvis > 0 and opt.s2e_src == 'tar':
    # when opt.s2e_src==tar, use target information (transfer_gt mode)
    print('visulizing first %d samples ("transfer_gt" mode)' % opt.test_nvis)
    num_vis_batch = int(np.ceil(1.0*opt.test_nvis/opt.batch_size))
    val_visuals = None
    for i, data in enumerate(val_loader):
        if i == num_vis_batch:
            break
        model.set_input(data)
        model.test(mode='transfer_gt', compute_loss=False)
        visuals = model.get_current_visuals()
        if val_visuals is None:
            val_visuals = visuals
        else:
            for name, v in visuals.iteritems():
                val_visuals[name][0] = torch.cat((val_visuals[name][0], v[0]),dim=0)
    visualizer.visualize_image(epoch = opt.which_epoch+'(gt)', subset = 'test', visuals = val_visuals)

if opt.vis_only:
    exit()


# test
loss_buffer = LossBuffer(size=len(val_loader))

if not opt.reconstruct_ref:
    # normal mode
    if opt.save_output:
        img_dir = os.path.join(model.save_dir, 'test')
        io.mkdir_if_missing(img_dir)
        if opt.save_seg:
            seg_dir = os.path.join(model.save_dir, 'test_seg')
            io.mkdir_if_missing(seg_dir)

    for i, data in enumerate(tqdm.tqdm(val_loader, desc='Testing')):
        if opt.nbatch > 0 and i == opt.nbatch:
            break
        model.set_input(data)
        model.test(compute_loss=False)
        loss_buffer.add(model.get_current_errors())
        # save output
        if opt.save_output:
            id_list = model.input['id']
            images = model.output['img_out'].cpu().numpy().transpose(0,2,3,1)
            images = ((images + 1.0) * 127.5).clip(0,255).astype(np.uint8)
            for (id1, id2), img in zip(id_list, images):
                img = img[:,:,[2,1,0]] # convert to BGR channel order for cv2
                cv2.imwrite(os.path.join(img_dir,'%s_%s.jpg' % (id1, id2)), img)

            if opt.save_seg:
                assert 'seg' in opt.output_type
                segs = model.output['seg_out'].max(dim=1)[1] # size (bsz, h, w)
                segs = segs.cpu().numpy().astype(np.uint8)
                for (id1, id2), seg in zip(id_list, segs):
                    cv2.imwrite(os.path.join(seg_dir, '%s_%s.bmp' % (id1, id2)), seg)
else:
    # reconstruct image_ref
    if opt.save_output:
        img_dir = os.path.join(model.save_dir, 'test_ref')
        io.mkdir_if_missing(img_dir)
        if opt.save_seg:
            seg_dir = os.path.join(model.save_dir, 'test_seg_ref')
            io.mkdir_if_missing(seg_dir)

    for i, data in enumerate(tqdm.tqdm(val_loader, desc='Testing')):
        if opt.nbatch > 0 and i == opt.nbatch:
            break
        model.set_input(data)
        model.test(mode='reconstruct_ref', compute_loss=False)
        loss_buffer.add(model.get_current_errors())
        # save output
        if opt.save_output:
            id_list = model.input['id']
            images = model.output['img_out'].cpu().numpy().transpose(0,2,3,1)
            images = ((images + 1.0) * 127.5).clip(0,255).astype(np.uint8)
            for (id1, id2), img in zip(id_list, images):
                img = img[:,:,[2,1,0]] # convert to BGR channel order for cv2
                cv2.imwrite(os.path.join(img_dir,'%s_%s.jpg' % (id1, id2)), img)

            if opt.save_seg:
                assert 'seg' in opt.output_type
                segs = model.output['seg_out'].max(dim=1)[1] # size (bsz, h, w)
                segs = segs.cpu().numpy().astype(np.uint8)
                for (id1, id2), seg in zip(id_list, segs):
                    cv2.imwrite(os.path.join(seg_dir, '%s_%s.bmp' % (id1, id2)), seg)


test_error = loss_buffer.get_errors()
print('\n')
visualizer.print_error(test_error)
