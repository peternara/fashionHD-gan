from __future__ import division, print_function

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import networks
from torch.autograd import Variable
from misc.image_pool import ImagePool
from base_model import BaseModel
import network_loader

import os
import sys
import numpy as np
import time
from collections import OrderedDict
import util.io as io

class MultimodalDesignerGAN_V2(BaseModel):
    '''
    modules:
        encoders: Es, Ee and Ec
        netG_LR: low resolution generator for feature fusion
        netG_HR: high resolution generator for image generation
        netD: discriminator
        netD_feat: feature level discriminator?
    '''
    def name(self):
        return 'MultimodalDesignerGAN_V2'

    def initialize(self, opt):
        super(MultimodalDesignerGAN_V2, self).initialize(opt)
        ###################################
        # define networks
        ###################################
        self.modules = {}
        # shape branch
        self.shape_encoder = networks.define_image_encoder(opt, 'shape')
        self.modules['shape_encoder'] = self.shape_encoder
        # edge branch
        if self.use_edge:
            self.edge_encoder = networks.define_image_encoder(opt, 'edge')
            self.modules['edge_encoder'] = self.edge_encoder
        else:
            self.encoder_edge = None
        # color branch
        if self.use_color:
            self.color_encoder = networks.define_image_encoder(opt, 'color')
            self.modules['color_encoder'] = self.color_encoder
        else:
            self.color_encoder = None

        # fusion model
        if opt.fusion_model == 'concat':
            # shape_feat, edge_feat and color_feat will be simply upmpled to same size (size of shape_feat) and concatenated
            pass
        elif opt.fusion_model == 'fusion':
            # edge_feat & color_feat feature will be upsampled (if needed) to the size of shape_feat. They will be concatenated an fed into a stack of residual blocks
            assert opt.use_edge or opt.use_color
            feat_nc = (opt.edge_nof if opt.use_edge else 0) + (opt.color_nof if opt.use_color else 0)
            guide_nc = opt.shape_nof
            output_nc = feat_nc + guide_nc
            self.fusion_net = networks.define_feature_fusion_network(name='FeatureFusionNetwork', feat_nc=feat_nc, guide_nc=guide_nc, output_nc=output_nc, nblocks=opt.mid_nblocks,
                norm=opt.norm, gpu_ids=self.gpu_ids, init_type=opt.init_type)
            self.modules['fusion_net'] = self.fusion_net
        elif opt.fusion_model == 'trans':
            # edge_feat/color_feat will be separately transfered, guided by input shape_feat and target_shape_feat
            if self.use_edge:
                self.edge_trans_net = networks.define_feature_fusion_network(name='FeatureTransNetwork', feat_nc=opt.edge_nof, guide_nc=opt.shape_nof, nblocks=opt.mid_nblocks, 
                    ndowns=opt.mid_ndowns, norm=opt.norm, gpu_ids=self.gpu_ids, init_type=opt.init_type)
                self.modules['edge_trans_net'] = self.edge_trans_net
            if self.use_color:
                self.color_trans_net = networks.define_feature_fusion_network(name='FeatureTransNetwork', feat_nc=opt.color_nof, guide_nc=opt.shape_nof, nblocks=opt.mid_nblocks,
                    ndowns=opt.mid_nblocks, norm=opt.norm, gpu_ids=self.gpu_ids, init_type=opt.init_type)
                self.modules['color_trans_net'] = self.color_trans_net

        # netG
        self.netG = networks.define_upsample_generator(opt)
        self.modules['netG'] = self.netG

        # netD
        if self.is_train:
            self.netD = networks.define_D(opt)
            self.modules['netD'] = self.netD

        ###################################
        # load weights
        ###################################
        if self.is_train:
            if opt.continue_train:
                for label, net in self.modules.iteritems():
                    self.load_network(net, label, opt.which_epoch)
            else:
                if opt.which_model_init != 'none':
                    for label, net in self.modules.iteritems():
                        self.load_network(net, label, 'latest', opt.which_model_init, forced=False)
        else:
            for label, net in self.modules.iteritems():
                if label != 'netD':
                    self.load_network(net, label, opt.which_epoch)

        ###################################
        # prepare for training
        ###################################
        if self.is_train:
            self.fake_pool = ImagePool(opt.pool_size)
            ###################################
            # define loss functions
            ###################################
            self.loss_functions = []
            if opt.which_gan in {'dcgan', 'lsgan'}:
                self.crit_GAN = networks.GANLoss(use_lsgan = opt.which_gan == 'lsgan', tensor = self.Tensor)
                self.loss_functions.append(self.crit_GAN)
            else:
                # WGAN loss will be calculated in self.backward_D_wgangp and self.backward_G
                self.crit_GAN = None

            self.crit_L1 = nn.L1Loss()
            self.loss_functions.append(self.crit_L1)

            if self.opt.loss_weight_vgg > 0:
                self.crit_vgg = networks.VGGLoss(self.gpu_ids)
                self.loss_functions.append(self.crit_vgg)

            self.crit_psnr = networks.SmoothLoss(networks.PSNR())
            self.loss_functions.append(self.crit_psnr)
            ###################################
            # create optimizers
            ###################################
            self.schedulers = []
            self.optimizers = []

            # G optimizer
            G_module_list = ['shape_encoder', 'edge_encoder', 'color_encoder', 'netG', 'fusion_net']
            G_param_groups = [{'params': net.parameters()} for m in G_module_list if m in self.modules]
            self.optim_G = torch.optim.Adam(G_param_groups, lr=opt.lr, betas=(opt.beta1, opt.beta2))
            self.optimizers.append(self.optim_G)
            # D optimizer
            self.optim_D = torch.optim.Adam(self.netD.parameters(), lr=opt.lr_D, betas=(opt.beta1, opt.beta2))
            self.optimizers.append(self.optim_D)
            # feature transfer network optimizer
            FTN_module_list = ['edge_trans_net', 'color_trans_net']
            FTN_param_groups = [{'params': net.parameters()} for m in FTN_module_list if m in self.modules]
            if len(FTN_param_groups) > 0:
                self.optim_FTN = torch.optim.Adam(FTN_param_groups, lr=opt.lr, betas(opt.beta1, opt.beta2))
                self.optimizers.append(self.optim_FTN)
            else:
                self.optim_FFN = None
            # schedulers
            for optim in self.optimizers:
                self.schedulers.append(networks.get_scheduler(optim, opt))

    def set_input(self, data):
        self.input['img'] = self.Tensor(data['img'].size()).copy_(data['img'])
        self.input['attr_label'] = self.Tensor(data['attr_label'].size()).copy_(data['attr_label'])
        self.input['lm_map'] = self.Tensor(data['lm_map'].size()).copy_(data['lm_map'])
        self.input['seg_mask'] = self.Tensor(data['seg_mask'].size()).copy_(data['seg_mask'])
        self.input['seg_map'] = self.Tensor(data['seg_map'].size()).copy_(data['seg_map'])
        self.input['edge_map'] = self.Tensor(data['edge_map'].size()).copy_(data['edge_map'])
        self.input['color_map'] = self.Tensor(data['color_map'].size()).copy_(data['color_map'])
        self.input['id'] = data['id']

        if self.opt.affine_aug:
            self.input['seg_mask_aug'] = self.Tensor(data['seg_mask_aug'].size()).copy_(data['seg_mask_aug'])
            self.input['edge_map_aug'] = self.Tensor(data['edge_map_aug'].size()).copy_(data['edge_map_aug'])
            self.input['color_map_aug'] = self.Tensor(data['color_map_aug'].size()).copy_(data['color_map_aug'])
            self.input['lm_map_aug'] = self.Tensor(data['lm_map_aug'].size()).copy_(data['lm_map_aug'])

        # create input variables
        for k, v in self.input.iteritems():
            if isinstance(v, torch.tensor._TensorBase):
                self.input[k] = Variable(v)

    def get_shape_repr(self, lm_map, seg_mask, edge_map):
        if self.opt.shape_encode == 'lm':
            shape_repr = lm_map
        elif self.opt.shape_encode == 'seg':
            shape_repr = seg_mask
        elif self.opt.shape_encode == 'lm+seg':
            shape_repr = torch.cat((lm_map, seg_mask), dim = 1)
        elif self.opt.shape_encode == 'seg+e':
            shape_repr = torch.cat((seg_mask, edge_map), dim = 1)
        elif self.opt.shape_encode == 'lm+seg+e':
            shape_repr = torch.cat((lm_map, seg_mask, edge_map), dim = 1)
        elif self.opt.shape_encode == 'e':
            shape_repr = edge_map
        return shape_repr

    def encode_shape(self, shape_repr):
        return self.shape_encoder(shape_repr)

    def encode_edge(self, input, shape_repr):
        if self.opt.edge_shape_guided:
            input = torch.cat((input, shape_repr))
        return self.edge_encoder(input)

    def encode_color(self, input, shape_repr):
        if self.opt.color_shape_guided:
            input = torch.cat((input, shape_repr))
        return self.color_encoder(input)
    
    def align_and_concat(self, inputs, size):
        for i, x in enumerate(inputs):
            if not (self.size(2)==size[0] and self.size(3)==size[1]):
                inputs[i] = F.upsample(x, size, mode='bilinear')
        output = torch.cat(inputs, dim=1)
        return output

    def forward(self, check_grad=False):
        ###################################
        # encode shape, edge and color
        ###################################
        # shape repr and shape feat
        self.output['shape_repr'] = self.get_shape_repr(self.input['lm_map'], self.input['seg_mask'], self.input['edge_map'])
        self.output['shape_feat'] = self.encode_shape(self.output['shape_repr'])
        # edge feat
        if self.use_edge:
            self.output['edge_feat'] = self.encode_edge(self.input['edge_map'], self.output['shape_repr'])
        # color feat
        if self.use_color:
            self.output['color_feat'] = self.encode_color(self.input['color_map'], self.output['shape_repr'])
        ###################################
        # feature fusion
        ###################################
        if self.opt.fusion_model == 'concat':
            feat = [self.output[k] for k in ['shape_feat', 'edge_feat', 'color_feat'] if k in self.output]
            self.output['feat'] = self.align_and_concat(feat, self.output['shape_feat'].size()[2:4])
        
        elif self.opt.fusion_model == 'fusion':
            feat = [self.output[k] for k in ['edge_feat', 'color_feat'] if k in self.output]
            feat = self.align_and_concat(feat, self.output['shape_feat'].size()[2:4])
            self.output['feat'] = self.fusion_net(feat, self.output['shape_feat'])
        
        elif self.opt.fusion_model == 'trans':
            feat = [self.output[k] for k in ['shape_feat', 'edge_feat', 'color_feat'] if k in self.output]
            self.output['feat'] = self.align_and_concat(feat, self.output['shape_feat'].size()[2:4])
            # feature transfer
            self.transfer_feature()
            feat_trans = [self.output[k] for k in ['shape_feat_trans', 'edge_feat_trans', 'color_feat_trans'] if k in self.output]
            self.output['feat_trans'] = self.align_and_concat(feat_trans, self.output['shape_feat'].size()[2:4])
        ###################################
        # netG
        ###################################



    def transfer_feature(self):
        # tansfer edge / color feature
        if self.is_train and self.opt.affine_aug:
            self.output['shape_repr_aug'] = self.get_shape_repr(self.input['lm_map_aug'], self.input['seg_mask_aug'], self.input['edge_map_aug'])
            self.output['shape_feat_aug'] = self.encode_shape(self.output['shape_repr_aug'])
            if self.opt.use_edge:
                self.output['edge_feat_aug'] = self.encode_edge(self.input['edge_map_aug'], self.output['shape_repr_aug'])
                self.output['edge_feat_trans'] = self.edge_trans_net(feat=self.output['edge_feat_aug'], input_guide=self.output['shape_feat_aug'], output_guide=self.output['shape_feat'])
            if self.opt.use_color:
                self.output['color_feat_aug'] = self.encode_color(self.input['color_map_aug'], self.output['shape_repr_aug'])
                self.output['color_feat_trans'] = self.color_trans_net(feat=self.output['color_feat_aug'], input_guide=self.output['shape_feat_aug'], output_guide=self.output['shape_feat'])
        else:
            if self.use_edge:
                self.output['edge_feat_trans'] = self.edge_trans_net(feat=self.output['edge_feat'], input_guide=self.output['shape_feat'], output_guide=self.output['shape_feat'])
            if self.use_color:
                self.output['color_feat_trans'] = self.color_trans_net(feat=self.output['color_feat'], input_guide=self.output['shape_feat'], output_guide=self.output['shape_feat'])

    def test(self):
        if float(torch.__version__[0:3]) >= 0.4:
            with torch.no_grad():
                self.forward()
        else:
            for k,v in self.input.iteritems():
                if isinstance(v, Variable):
                    v.volatile = True
            self.forward()