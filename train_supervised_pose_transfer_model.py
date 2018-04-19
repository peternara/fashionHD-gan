from __future__ import division, print_function

import torch
from models.supervised_pose_transfer_model import SupervisedPoseTransferModel
from data.data_loader import CreateDataLoader
from options.pose_transfer_options import TrainPoseTransferOptions
from misc.visualizer import GANVisualizer_V3
from misc.loss_buffer import LossBuffer

import util.io as io
import os
import sys
import time
import numpy as np
from collections import OrderedDict

opt = TrainPoseTransferOptions().parse()
# create model
model = SupervisedPoseTransferModel()
model.initialize(opt)
# create data loader
train_loader = CreateDataLoader(opt, split = 'train')
val_loader = CreateDataLoader(opt, split = 'test')
# create visualizer
visualizer = GANVisualizer_V3(opt)

pavi_upper_list = ['PSNR', 'SSIM']
pavi_lower_list = ['loss_L1', 'loss_vgg', 'loss_G', 'loss_D', 'loss_pose']

total_steps = 0

for epoch in range(opt.epoch_count, opt.niter + opt.niter_decay + 1):
    model.update_learning_rate()
    for i, data in enumerate(train_loader):
        total_steps += 1
        model.set_input(data)
        model.forward()
        model.optimize_parameters()

        if total_steps % opt.display_freq == 0:
            train_error = model.get_current_errors()
            visualizer.print_train_error(
                iter_num = total_steps,
                epoch = epoch, 
                num_batch = len(train_loader), 
                lr = model.optimizers[0].param_groups[0]['lr'], 
                errors = train_error)
            if opt.pavi:
                visualizer.pavi_log(phase = 'train', iter_num = total_steps, outputs = train_error, upper_list = pavi_upper_list, lower_list = pavi_lower_list)

    if epoch % opt.test_epoch_freq == 0:
        _ = model.get_current_errors()

        loss_buffer = LossBuffer(size=len(val_loader))

        for i, data in enumerate(val_loader):
            model.set_input(data)
            model.test(compute_loss=True)
            loss_buffer.add(model.get_current_errors())
            print('\rTesting %d/%d (%.2f%%)' % (i, len(val_loader), 100.*i/len(val_loader)), end = '')
            sys.stdout.flush()
        print('\n')

        test_error = loss_buffer.get_errors()
        visualizer.print_test_error(iter_num = total_steps, epoch=epoch, errors = test_error)
        if opt.pavi:
            visualizer.pavi_log(phase = 'test', iter_num = total_steps, outputs = test_error, upper_list = pavi_upper_list, lower_list = pavi_lower_list)


    if epoch % opt.vis_epoch_freq == 0:
        train_data = iter(train_loader).next()
        model.set_input(train_data)
        model.test()
        train_visuals = model.get_current_visuals()
        visualizer.visualize_image(epoch = epoch, subset = 'train', visuals = train_visuals)

        val_data = iter(val_loader).next()
        model.set_input(val_data)
        model.test()
        val_visuals = model.get_current_visuals()
        visualizer.visualize_image(epoch = epoch, subset = 'test', visuals = val_visuals)
    
    if epoch % opt.save_epoch_freq == 0:
        model.save(epoch)
    model.save('latest')
