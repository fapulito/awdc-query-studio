# Image Assets Directory

This directory contains branding and metadata images for the chatbot application.

## Files Overview

### Favicons
- **favicon.svg** - SVG favicon (scalable, modern browsers)
- **favicon-16x16.png** - 16x16 PNG favicon
- **favicon-32x32.png** - 32x32 PNG favicon
- **apple-touch-icon.png** - 180x180 PNG for iOS home screen

### Social Media Images
- **og-image.png** - 1200x630 PNG for Open Graph (Facebook, LinkedIn)
- **twitter-card.png** - 1200x600 PNG for Twitter/X cards

### Application Logo
- **logo.png** - Application logo for UI elements

## Replacing Placeholder Images

The current files are placeholders. To add your custom branding:

### 1. Favicon Files
Create favicons from your logo or design:
- Use online tools like [Favicon.io](https://favicon.io/) or [RealFaviconGenerator](https://realfavicongenerator.net/)
- Upload your logo or design
- Download the generated favicon files
- Replace the placeholder files in this directory

**Requirements:**
- `favicon-16x16.png`: 16x16 pixels, PNG format
- `favicon-32x32.png`: 32x32 pixels, PNG format
- `apple-touch-icon.png`: 180x180 pixels, PNG format, solid background (no transparency)

### 2. Social Media Images
Create preview images for social sharing:

**Open Graph Image (og-image.png):**
- Size: 1200x630 pixels (1.91:1 aspect ratio)
- Format: PNG or JPG
- Max file size: 8MB
- Include: App name, tagline, branded visuals
- High contrast for readability

**Twitter Card Image (twitter-card.png):**
- Size: 1200x600 pixels (2:1 aspect ratio)
- Format: PNG or JPG
- Max file size: 5MB
- Include: App name, tagline, branded visuals

**Design Tips:**
- Use your brand colors
- Include the app name prominently
- Add a short tagline or description
- Ensure text is readable at small sizes
- Test how it looks in social media previews

### 3. Application Logo
Replace `logo.png` with your application logo:
- Recommended size: 256x256 pixels or larger
- Format: PNG with transparent background
- Use for UI header or branding elements

## Tools for Creating Images

### Favicon Generators
- [Favicon.io](https://favicon.io/) - Generate from text, image, or emoji
- [RealFaviconGenerator](https://realfavicongenerator.net/) - Comprehensive favicon generator

### Image Editors
- [Canva](https://www.canva.com/) - Easy-to-use design tool with templates
- [Figma](https://www.figma.com/) - Professional design tool
- [GIMP](https://www.gimp.org/) - Free open-source image editor
- [Photoshop](https://www.adobe.com/products/photoshop.html) - Professional image editor

### Social Media Preview Tools
- [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)
- [LinkedIn Post Inspector](https://www.linkedin.com/post-inspector/)

## Verification

After replacing the images, verify they appear correctly:

1. **Favicon**: Check browser tab icon
2. **Apple Touch Icon**: Add to iOS home screen and check icon
3. **Open Graph**: Share a link on Facebook/LinkedIn and check preview
4. **Twitter Card**: Share a link on Twitter/X and check preview

## Configuration

Image paths are configured in `config.py` under the `MetadataConfig` class. The default paths point to this directory. If you need to change paths or add additional images, update the configuration accordingly.
