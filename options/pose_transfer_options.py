from base_options import BaseOptions

class BasePoseTransferOptions(BaseOptions):
    def initialize(self):
        super(BasePoseTransferOptions, self).initialize()
        parser = self.parser
        ##############################
        # General Setting
        ##############################
        parser.add_argument('--norm', type=str, default='instance', help='instance normalization or batch normalization [batch|instance|none]')
        parser.add_argument('--no_dropout', action='store_true', help='no dropout for the generator')
        parser.add_argument('--batch_size', type = int, default = 32, help = 'batch size')
        parser.add_argument('--pavi', default = False, action = 'store_true', help = 'activate pavi log')
        ##############################
        # Pose Setting
        ##############################
        parser.add_argument('--pose_type', type=str, default='joint', choices=['joint', 'joint+seg'], help='pose format')
        parser.add_argument('--joint_radius', type=int, default=10, help='radius of joint map')
        parser.add_argument('--seg_bin_size', type=int, default=16, help='bin size of downsampled seg mask')        
        ##############################
        # Transformer Setting
        ##############################
        parser.add_argument('--which_model_T', type=str, default='unet', choices=['unet', 'resnet'], help='pose transfer network architecture')
        parser.add_argument('--T_nf', type=int, default=64, help='output channel number of the first conv layer in netT')
        ##############################
        # Discriminator Setting
        ##############################
        parser.add_argument('--which_gan', type=str, default='lsgan', choices=['dcgan', 'lsgan'], help='gan loss type')
        parser.add_argument('--D_nf', type=int, default=64, help='output channel number of the first conv layer in netD')
        parser.add_argument('--D_cond', type=int, default=0, choices=[0,1], help='use conditioned discriminator')
        parser.add_argument('--pool_size', type=int, default=50, help='size of fake pool')
        ##############################
        # data setting (dataset_mode == pose_transfer_dataset)
        ##############################
        parser.add_argument('--dataset_mode', type=str, default='pose_transfer', help='type of dataset. see data/data_loader.py')
        parser.add_argument('--data_root', type=str, default='datasets/DF_Pose/')
        parser.add_argument('--fn_split', type=str, default='Label/pair_split.json')
        parser.add_argument('--img_dir', type=str, default='Img/img_df/')
        parser.add_argument('--seg_dir', type=str, default='Img/seg_df/')
        parser.add_argument('--fn_pose', type=str, default='Label/pose_label.pkl')
        parser.add_argument('--debug', action='store_true', help='debug')

    def auto_set(self):
        super(BasePoseTransferOptions, self).auto_set()
        opt = self.opt
        ###########################################
        # Add id profix
        ###########################################
        if not opt.id.startswith('PoseTransfer_'):
            opt.id = 'PoseTransfer_' + opt.id


class TrainPoseTransferOptions(BasePoseTransferOptions):
    def initialize(self):
        super(TrainPoseTransferOptions, self).initialize()
        parser = self.parser
        # basic
        parser.add_argument('--continue_train', action = 'store_true', default = False, help = 'coninue training from saved model')
        # optimizer
        parser.add_argument('--lr', type = float, default = 2e-4, help = 'initial learning rate')
        parser.add_argument('--lr_D', type = float, default = 2e-5, help = 'only use lr_D for netD when loss_weight_gan > 0')
        parser.add_argument('--beta1', type = float, default = 0.5, help = 'momentum1 term for Adam')
        parser.add_argument('--beta2', type = float, default = 0.999, help = 'momentum2 term for Adam')
        # scheduler
        parser.add_argument('--lr_policy', type=str, default='step', choices = ['step', 'plateau', 'lambda'], help='learning rate policy: lambda|step|plateau')
        parser.add_argument('--epoch_count', type=int, default=1, help='the starting epoch count, we save the model by <epoch_count>, <epoch_count>+<save_latest_freq>, ...')
        parser.add_argument('--niter', type = int, default=30, help = '# of iter at starting learning rate')
        parser.add_argument('--niter_decay', type=int, default=0, help='# of iter to linearly decay learning rate to zero')
        parser.add_argument('--lr_decay', type=int, default=10, help='multiply by a gamma every lr_decay_interval epochs')
        parser.add_argument('--lr_gamma', type = float, default = 0.1, help='lr decay rate')
        parser.add_argument('--display_freq', type = int, default = 10, help='frequency of showing training results on screen')
        parser.add_argument('--test_epoch_freq', type = int, default = 1, help='frequency of testing model')
        parser.add_argument('--save_epoch_freq', type = int, default = 5, help='frequency of saving model to disk' )
        parser.add_argument('--vis_epoch_freq', type = int, default = 1, help='frequency of visualizing generated images')
        parser.add_argument('--max_n_vis', type = int, default = 32, help='max number of visualized images')
        # loss weights
        parser.add_argument('--loss_weight_L1', type=float, default=1)
        parser.add_argument('--loss_weight_vgg', type=float, default=1)
        parser.add_argument('--loss_weight_gan', type=float, default=0., help='set loss_weight_gan > 0 to enable GAN loss')
        # set train
        self.is_train = True

class TestPoseTransferOptions(BasePoseTransferOptions):
    def initialize(self):
        super(TestPoseTransferOptions, self).initialize()
        self.is_train = False