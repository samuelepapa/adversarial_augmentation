# math
# plotting
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
# dnn
import torch
import torch.nn as nn
import torchvision
from matplotlib.offsetbox import (OffsetImage, AnnotationBbox)
from numpy import iscomplexobj
from numpy import trace
from scipy.linalg import sqrtm

# custom library
import augment


def compute_bin(conf_thresh_lower, conf_thresh_upper, conf, pred, true):
    filtered = [x for x in zip(pred, true, conf) if x[2] > conf_thresh_lower and x[2] <= conf_thresh_upper]
    if len(filtered) < 1:
        return 0, 0, 0
    else:
        correct = len([x for x in filtered if x[0] == x[1]])  # How many correct labels
        len_bin = len(filtered)  # How many elements falls into given bin
        avg_conf = sum([x[2] for x in filtered]) / len_bin  # Avg confidence of BIN
        accuracy = float(correct) / len_bin  # accuracy of BIN
        return accuracy, avg_conf, len_bin


def cal_statistics(target, pred_log_prob, nclasses=10):
    probs = torch.stack(pred_log_prob).exp().view(-1, nclasses)
    nimages = probs.shape[0]

    target_labels = torch.stack(target).view(-1)
    pred_conf, pred_labels = [i.view(-1) for i in probs.max(1, keepdim=True)]
    pred_acc = ((pred_labels == target_labels).sum()).type(torch.DoubleTensor).div(nimages)
    pred_err_percent = 1 - pred_acc
    return pred_acc, pred_conf, pred_labels, target_labels, pred_err_percent


def get_bins(target, pred_log_prob, nclasses=10):
    bin_size = 0.1
    upper_bnd = np.arange(bin_size, 1 + bin_size, bin_size)
    ece = 0

    # get statistics
    pred_acc, pred_conf, pred_labels, target_labels, pred_err_percent = cal_statistics(target, pred_log_prob)
    n = len(pred_conf)

    # store bins
    bin_accs = []
    bin_confs = []
    bin_lens = []

    # ECE and loop through each bin given by bound
    for conf_thresh in upper_bnd:
        acc, avg_conf, len_bin = compute_bin(conf_thresh - bin_size, conf_thresh, pred_conf, pred_labels, target_labels)
        bin_accs.append(acc)
        bin_confs.append(avg_conf)
        bin_lens.append(len_bin)
        # Add weighting to ECE
        ece += np.abs(acc - avg_conf) * len_bin / n

    return ece, bin_accs, bin_confs, bin_lens


def reliability_diagram_plot(accs, confs, bin_size=0.1, title="Reliability Diagram", plot_n=1):
    import seaborn as sns
    sns.plotting_context("paper")
    sns.set_style("whitegrid")
    outputs = accs
    gap = confs

    positions = np.arange(0 + bin_size / 2, 1 + bin_size / 2, bin_size)

    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(4.5, 5))
    ax.grid(True, axis="y", linestyle="--", alpha=0.5, zorder=1)

    # Output
    output_plt = ax.bar(positions, outputs, width=bin_size, edgecolor="black", color="blue", alpha=1, label="Outputs",
                        zorder=2)

    # Gap
    gap_plt = ax.bar(positions, np.maximum(gap, outputs) - np.minimum(outputs, gap), bottom=np.minimum(outputs, gap),
                     width=bin_size, edgecolor="red", color="red", alpha=0.25, label="Gap", hatch='/', linewidth=2,
                     zorder=3)

    # Line plot with center line.
    ax.set_aspect('equal')

    ax.plot([0, 1], [0, 1], linestyle="dashed", zorder=4)
    ax.legend(handles=[output_plt, gap_plt])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title(title, fontsize=15)
    ax.set_xlabel("Confidence", fontsize=12, color="black")
    ax.set_ylabel("Accuracy", fontsize=12, color="black")
    return fig


# calculate frechet inception distance
def calculate_fid(image1, image2):
    # calculate mean and covariance
    mu1, sigma1 = image1.mean(axis=0), np.cov(image1, rowvar=False)
    mu2, sigma2 = image2.mean(axis=0), np.cov(image2, rowvar=False)
    ss = np.sum((mu1 - mu2) ** 2.0)
    cov2 = sqrtm(sigma1.dot(sigma2))
    # if complex get real part
    if iscomplexobj(cov2):
        cov2 = cov2.real
    # calculate score
    fid = ss + trace(sigma1 + sigma2 - 2.0 * cov2)
    return fid


def get_features(model):
    modules = list(model.children())[:-1]
    model_feature = nn.Sequential(*modules)
    for p in model_feature.parameters():
        p.requires_grad = False
    return model_feature


def get_FID(inputs, model_features, device, augmentation="g", noise_level=[0, 10, 20, 30], bottleneck=False):
    n_input = inputs.shape[0]
    feature_input = model_features(inputs.to(device))
    if bottleneck:
        # adjust for resnet bottleneck expansion
        feature_input_num = feature_input.cpu().detach().numpy().reshape(n_input, 512 * 4)
    else:
        feature_input_num = feature_input.cpu().detach().numpy().reshape(n_input, 512)
    FID = []
    plot_batch = []
    for i in noise_level:
        if augmentation in ("flr", "flipr"):
            aug_batches, aug_seqs, aug_seqs_names = augment.compute_augmentations(inputs, augmentations=augmentation,
                                                                                  n=1,
                                                                                  depth=1,
                                                                                  flip_p=i)
        else:
            aug_batches, aug_seqs, aug_seqs_names = augment.compute_augmentations(inputs, augmentations=augmentation,
                                                                                  n=1,
                                                                                  depth=1,
                                                                                  noise=(i, i), rot=(i, i),
                                                                                  br_add=i,
                                                                                  crop_per=i)

        plot_batch.append(aug_batches[0][0])
        aug_features = model_features(aug_batches[0].to(device))
        aug_features_num = aug_features.cpu().detach().numpy().reshape(n_input, -1)
        FID.append(calculate_fid(feature_input_num, aug_features_num))
    plot_batch = torch.cat(plot_batch).reshape(len(noise_level), 3, 32, 32)
    return FID, plot_batch


def plot_fid(FID, plot_batch, x_labels=[0, 1, 2, 3], figsize=(10, 5), title="", xlabel="Noise",
             ylabel="FID", plot_path="figures/plot1.png"):
    sns.plotting_context("paper")
    sns.set_style("whitegrid")
    _, ax = plt.subplots(figsize=figsize)
    inp = torchvision.utils.make_grid(plot_batch)
    inp = inp.numpy().transpose((1, 2, 0))
    mean = np.array([0.4914, 0.4822, 0.4465])
    std = np.array([0.2023, 0.1994, 0.2010])
    inp = std * inp + mean
    inp = np.clip(inp, 0, 1)

    imagebox = OffsetImage(inp, zoom=2)
    imagebox.image.axes = ax
    ylim = np.max(FID) * 1.5
    xy = [1.5, ylim * 0.85]
    ab = AnnotationBbox(imagebox, xy,
                        xybox=(0, 0),
                        xycoords='data',
                        boxcoords="offset points",
                        pad=0,
                        )

    ax.add_artist(ab)

    ax.set_title(title)
    ax.set_xticks(list(range(len(x_labels))))
    ax.set_xticklabels(x_labels, fontsize=12)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)
    ax.set_ylim(0, ylim)
    ax.plot(FID, marker='*')
    plt.savefig(plot_path)


