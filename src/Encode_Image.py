"""
Encode_Image.py

This file contains the implementation of the Image Encoding function.
Authors:
- Alessio Borgi (alessioborgi3@gmail.com)
- Francesco Danese (danese.1926188@studenti.uniroma1.it)

Created on: July 6, 2024
"""


from __future__ import annotations
import torch
import numpy as np
from diffusers import StableDiffusionXLPipeline


def image_encoding(model: StableDiffusionXLPipeline, image: np.ndarray) -> T:

    # 1) Set VAE to Float32: Ensure the VAE operates in float32 precision for encoding.
    model.vae.to(dtype=torch.float32)

    # 2) Convert Image to PyTorch Tensor: Convert the input image from a numpy array to a PyTorch tensor and normalize pixel values to [0, 1].
    scaled_image = torch.from_numpy(image).float() / 255.

    # 3) Normalize and Prepare Image: Scale pixel values to the range [-1, 1], rearrange dimensions, and add batch dimension.
    permuted_image = (scaled_image * 2 - 1).permute(2, 0, 1).unsqueeze(0)

    # 4) Encode Image Using VAE: Use the VAE to encode the image into the latent space.
    latent_img = model.vae.encode(permuted_image.to(model.vae.device))['latent_dist'].mean * model.vae.config.scaling_factor

    # 5) Reset VAE to Float16: Optionally reset the VAE to float16 precision.
    model.vae.to(dtype=torch.float16)

    # 6) Return Latent Representation: Return the encoded latent representation of the image.
    return latent_img


### LINEAR WEIGHTED AVERAGE #################################
def images_encoding(model, images: list[np.ndarray], blending_weights: list[float]):
    """
    Encode a list of images using the VAE model and blend their latent representations
    according to the given blending_weights.

    Args:
    - model: The StableDiffusionXLPipeline model.
    - images: A list of numpy arrays, each representing an image.
    - blending_weights: A list of floats representing the blending weights for each image.
              The blending_weights should sum to 1.

    Returns:
    - blended_latent_img: The blended latent representation.
    """

    # Ensure the blending_weights sum to 1.
    assert len(images) == len(blending_weights), "The number of images and blending_weights must match."
    assert np.isclose(sum(blending_weights), 1.0), "blending_weights must sum to 1."

    # Set VAE to Float32 for encoding.
    model.vae.to(dtype=torch.float32)

    # Initialize blended latent representation as None.
    blended_latent_img = None

    for img, weight in zip(images, blending_weights):

        # Convert image to PyTorch tensor and normalize pixel values to [0, 1].
        scaled_image = torch.from_numpy(img).float() / 255.

        # Normalize and prepare image.
        permuted_image = (scaled_image * 2 - 1).permute(2, 0, 1).unsqueeze(0)

        # Encode image using VAE.
        latent_img = model.vae.encode(permuted_image.to(model.vae.device))['latent_dist'].mean * model.vae.config.scaling_factor

        # Blend the latent representation based on the weight.
        if blended_latent_img is None:
            blended_latent_img = latent_img * weight
        else:
            blended_latent_img += latent_img * weight

    # Reset VAE to Float16 if necessary.
    model.vae.to(dtype=torch.float16)

    # Return the blended latent representation.
    return blended_latent_img


### WEIGHTED SLERP (SPHERICAL LINEAR INTERPOLATION) ###
def weighted_slerp(weight, v0, v1):
    """Spherical linear interpolation with a weight factor."""
    v0_norm = v0 / torch.norm(v0, dim=-1, keepdim=True)
    v1_norm = v1 / torch.norm(v1, dim=-1, keepdim=True)
    dot_product = torch.sum(v0_norm * v1_norm, dim=-1, keepdim=True)
    omega = torch.acos(dot_product)
    sin_omega = torch.sin(omega)
    return (torch.sin((1.0 - weight) * omega) / sin_omega) * v0 + (torch.sin(weight * omega) / sin_omega) * v1

def images_encoding_slerp(model, images: list[np.ndarray], blending_weights: list[float]):
    """
    Encode a list of images using the VAE model and blend their latent representations
    using Weighted Spherical Interpolation (slerp) according to the given blending_weights.

    Args:
    - model: The StableDiffusionXLPipeline model.
    - images: A list of numpy arrays, each representing an image.
    - blending_weights: A list of floats representing the blending weights for each image.
                        The blending_weights should sum to 1.

    Returns:
    - blended_latent_img: The blended latent representation.
    """

    # Ensure the blending_weights sum to 1.
    assert len(images) == len(blending_weights), "The number of images and blending_weights must match."
    assert np.isclose(sum(blending_weights), 1.0), "blending_weights must sum to 1."

    # Set VAE to Float32 for encoding.
    model.vae.to(dtype=torch.float32)

    # Initialize blended latent representation as None.
    blended_latent_img = None

    # Iterate over images and weights
    for idx, (img, weight) in enumerate(zip(images, blending_weights)):
        # Convert image to PyTorch tensor and normalize pixel values to [0, 1].
        scaled_image = torch.from_numpy(img).float() / 255.

        # Normalize and prepare image.
        permuted_image = (scaled_image * 2 - 1).permute(2, 0, 1).unsqueeze(0)

        # Encode image using VAE.
        latent_img = model.vae.encode(permuted_image.to(model.vae.device))['latent_dist'].mean * model.vae.config.scaling_factor

        # Blend the latent representation using spherical interpolation
        if blended_latent_img is None:
            blended_latent_img = latent_img * weight  # Initialize with the first image
        else:
            blended_latent_img = weighted_slerp(weight, blended_latent_img, latent_img)  # Spherical interpolation

    # Reset VAE to Float16 if necessary.
    model.vae.to(dtype=torch.float16)

    # Return the blended latent representation.
    return blended_latent_img


### BARYCENTRIC INTERPOLATION ###
def barycentric_interpolation(latents: list[torch.Tensor], weights: list[float]) -> torch.Tensor:
    """
    Perform barycentric interpolation on a set of latent vectors.
    
    Args:
    - latents: A list of latent vectors (Tensors) to be blended.
    - weights: A list of weights for the corresponding latent vectors. These should sum to 1.
    
    Returns:
    - blended_latent: The blended latent vector.
    """
    assert len(latents) == len(weights), "Number of latents and weights must match."
    assert np.isclose(sum(weights), 1.0), "Weights must sum to 1."
    
    # Start with a zero tensor for the blended latent vector
    blended_latent = torch.zeros_like(latents[0])
    
    # Perform barycentric interpolation by summing the weighted latents
    for latent, weight in zip(latents, weights):
        blended_latent += latent * weight
    
    return blended_latent

def images_encoding_barycentric(model, images: list[np.ndarray], blending_weights: list[float]):
    """
    Encode a list of images using the VAE model and blend their latent representations
    using Barycentric Interpolation according to the given blending_weights.

    Args:
    - model: The StableDiffusionXLPipeline model.
    - images: A list of numpy arrays, each representing an image.
    - blending_weights: A list of floats representing the blending weights for each image.
                        The blending_weights should sum to 1.

    Returns:
    - blended_latent_img: The blended latent representation.
    """

    # Ensure the blending_weights sum to 1.
    assert len(images) == len(blending_weights), "The number of images and blending_weights must match."
    assert np.isclose(sum(blending_weights), 1.0), "blending_weights must sum to 1."

    # Set VAE to Float32 for encoding.
    model.vae.to(dtype=torch.float32)

    # List to store latent representations
    latent_representations = []

    # Encode each image and store its latent representation
    for img in images:
        # Convert image to PyTorch tensor and normalize pixel values to [0, 1].
        scaled_image = torch.from_numpy(img).float() / 255.

        # Normalize and prepare image.
        permuted_image = (scaled_image * 2 - 1).permute(2, 0, 1).unsqueeze(0)

        # Encode image using VAE.
        latent_img = model.vae.encode(permuted_image.to(model.vae.device))['latent_dist'].mean * model.vae.config.scaling_factor

        # Add the latent representation to the list
        latent_representations.append(latent_img)

    # Perform barycentric interpolation on the latent representations
    blended_latent_img = barycentric_interpolation(latent_representations, blending_weights)

    # Reset VAE to Float16 if necessary.
    model.vae.to(dtype=torch.float16)

    # Return the blended latent representation.
    return blended_latent_img


### RBF INTERPOLATION ###
import torch
import numpy as np

def gaussian_rbf(distances, epsilon=1.0):
    """Radial Basis Function using Gaussian kernel."""
    return torch.exp(-(epsilon * distances) ** 2)

def rbf_interpolation(latents: list[torch.Tensor], weights: list[float], epsilon: float = 1.0) -> torch.Tensor:
    """
    Perform Radial Basis Function (RBF) interpolation on a set of latent vectors.
    
    Args:
    - latents: A list of latent vectors (Tensors) to be blended.
    - weights: A list of weights for the corresponding latent vectors. These should sum to 1.
    - epsilon: A parameter that controls the spread of the Gaussian RBF.
    
    Returns:
    - blended_latent: The blended latent vector.
    """
    assert len(latents) == len(weights), "Number of latents and weights must match."
    assert np.isclose(sum(weights), 1.0), "Weights must sum to 1."
    
    # Convert list of latents to a tensor stack for easier computation
    latent_stack = torch.stack(latents)  # Shape: (N, C, H, W)
    
    # Compute pairwise distances between latent vectors
    distances = torch.cdist(latent_stack.view(len(latents), -1), latent_stack.view(len(latents), -1), p=2)  # Flatten for distance computation
    
    # Apply RBF to the distances to compute the influence of each latent vector
    rbf_weights = gaussian_rbf(distances, epsilon=epsilon)  # Shape: (N, N)
    
    # Normalize the RBF weights so they sum to 1 along the second dimension
    rbf_weights = rbf_weights / rbf_weights.sum(dim=1, keepdim=True)
    
    # Perform RBF interpolation: weighted sum of the latents based on RBF weights
    # Here we need to properly broadcast rbf_weights to match the latent_stack dimensions
    blended_latent = torch.einsum('ij,i...->j...', rbf_weights, latent_stack)  # Perform weighted sum

    return blended_latent  # Return the blended latent vector

def images_encoding_rbf(model, images: list[np.ndarray], blending_weights: list[float], epsilon: float = 1.0):
    """
    Encode a list of images using the VAE model and blend their latent representations
    using Radial Basis Function (RBF) Interpolation according to the given blending_weights.

    Args:
    - model: The StableDiffusionXLPipeline model.
    - images: A list of numpy arrays, each representing an image.
    - blending_weights: A list of floats representing the blending weights for each image.
                        The blending_weights should sum to 1.
    - epsilon: A parameter that controls the spread of the RBF (default is 1.0).

    Returns:
    - blended_latent_img: The blended latent representation.
    """

    # Ensure the blending_weights sum to 1.
    assert len(images) == len(blending_weights), "The number of images and blending_weights must match."
    assert np.isclose(sum(blending_weights), 1.0), "blending_weights must sum to 1."

    # Set VAE to Float32 for encoding.
    model.vae.to(dtype=torch.float32)

    # List to store latent representations
    latent_representations = []

    # Encode each image and store its latent representation
    for img in images:
        # Convert image to PyTorch tensor and normalize pixel values to [0, 1].
        scaled_image = torch.from_numpy(img).float() / 255.

        # Normalize and prepare image.
        permuted_image = (scaled_image * 2 - 1).permute(2, 0, 1).unsqueeze(0)

        # Encode image using VAE.
        latent_img = model.vae.encode(permuted_image.to(model.vae.device))['latent_dist'].mean * model.vae.config.scaling_factor

        # Add the latent representation to the list
        latent_representations.append(latent_img)

    # Perform RBF interpolation on the latent representations
    blended_latent_img = rbf_interpolation(latent_representations, blending_weights, epsilon=epsilon)

    # Reset VAE to Float16 if necessary.
    model.vae.to(dtype=torch.float16)

    # Return the blended latent representation.
    return blended_latent_img